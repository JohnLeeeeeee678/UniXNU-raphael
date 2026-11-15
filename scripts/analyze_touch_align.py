#!/usr/bin/env python3
"""Locate the SweetHID touch offset expression and the framebuffer counterpart.

0061 presents the screen as the iPhone X panel (1125x2436 logical) and centres
the real panel inside that logical area.  SweetFramebuffer derives the offset
from the real panel size it reads from the device tree, SweetHID has no such
information and uses the hard coded guacamole panel size (1080x2400).

This tool
  * finds every instruction that reads the SweetHID constant pool,
  * dumps the enclosing function so the arithmetic can be read off the
    disassembly instead of guessed,
  * evaluates the expression for the stored constants so the numbers can be
    checked.
"""
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_edge_const import load_commands  # noqa: E402

# File offsets of the interesting constant pool words.
POOL_WORDS = {
    0x28A40: "shared native dims (1080, 2400) - framebuffer + HID",
    0x28AE0: "HID native dims (1080, 2400)",
    0x28AE4: "HID native dims [1] (2400)",
    0x28AE8: "HID addend A (200, 160)",
    0x28AEC: "HID addend A [1] (160)",
    0x28AF0: "HID mask B (126, 114)",
    0x28AF4: "HID mask B [1] (114)",
}


def text_section(data):
    best = None
    for seg in load_commands(data):
        for sec in seg["sections"]:
            if sec["name"] == "__text" and sec["size"]:
                if best is None or sec["size"] > best["size"]:
                    best = sec
    if best is None:
        raise SystemExit("no __text section")
    return best


def const_info(data):
    """Return (section vmaddr, section file offset) of __const."""
    for seg in load_commands(data):
        for sec in seg["sections"]:
            if sec["name"] == "__const":
                return sec["addr"], sec["offset"]
    raise SystemExit("no __const section")


def collect(path):
    data = open(path, "rb").read()
    text = text_section(data)
    const_addr, const_off = const_info(data)
    code = data[text["offset"]:text["offset"] + text["size"]]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    insns = [i for i in md.disasm(code, text["addr"]) if i.mnemonic != ".byte"]
    return data, text, const_addr, const_off, insns


def find_pool_loads(insns, const_addr, const_off, wanted):
    """LDR instructions that read one of the wanted constant pool words."""
    hits = []
    for idx, ins in enumerate(insns):
        if ins.mnemonic != "adrp":
            continue
        page = ins.operands[1].imm & 0xFFFFFFFFFFFFFFFF
        base_reg = ins.operands[0].reg
        for j in range(idx + 1, min(idx + 6, len(insns))):
            nxt = insns[j]
            if nxt.mnemonic.startswith("ldr") and len(nxt.operands) >= 2:
                mem = nxt.operands[1].mem
                if mem.base != base_reg:
                    continue
                vm = page + (mem.disp or 0)
                if not (const_addr <= vm < const_addr + 0x40000):
                    continue
                foff = const_off + (vm - const_addr)
                if foff in wanted:
                    hits.append({
                        "adrp": ins.address, "ldr": nxt.address,
                        "mnemonic": nxt.mnemonic, "op": nxt.op_str,
                        "vm": vm, "foff": foff,
                    })
                break
    return hits


def dump_pool(data):
    print("=== constant pool words ===")
    for off, label in sorted(POOL_WORDS.items()):
        vals = struct.unpack_from("<i", data, off)[0]
        print("  0x%06x  %-12d %s" % (off, vals, label))


def evaluate(data):
    """Evaluate the SWAR offset expression for the stored constants."""
    native = struct.unpack_from("<2i", data, 0x28AE0)
    addend = struct.unpack_from("<2i", data, 0x28AE8)
    mask = struct.unpack_from("<2i", data, 0x28AF0)
    logical = (1125, 2436)
    print("\n=== SWAR evaluation (logical 1125x2436) ===")
    print("  native  = %s" % (native,))
    print("  addend  = %s" % (addend,))
    print("  mask    = %s" % (mask,))
    for lane in (0, 1):
        v = ((logical[lane] + addend[lane]) >> 1) & mask[lane]
        print("  lane %d: ((%d + %d) >> 1) & %d = %d"
              % (lane, logical[lane], addend[lane], mask[lane], v))
    print("  -> fOff = (%d, %d)" % (
        ((logical[0] + addend[0]) >> 1) & mask[0],
        ((logical[1] + addend[1]) >> 1) & mask[1]))
    print("  framebuffer expects (22, 48) for the 1080x2340 panel")


def main(path):
    data, text, const_addr, const_off, insns = collect(path)
    print("__text  vm=0x%x off=0x%x size=0x%x" % (text["addr"], text["offset"], text["size"]))
    print("__const vm=0x%x off=0x%x" % (const_addr, const_off))
    dump_pool(data)
    evaluate(data)

    hits = find_pool_loads(insns, const_addr, const_off, set(POOL_WORDS))
    print("\n=== code references to the pool words of interest ===")
    seen = set()
    for h in hits:
        key = (h["foff"], h["ldr"])
        if key in seen:
            continue
        seen.add(key)
        print("  0x%x: %-22s ->  file 0x%06x  vm 0x%x" % (
            h["ldr"], h["op"], h["foff"], h["vm"]))
    if not seen:
        print("  (none)")

    # Dump the function that reads the HID pool, so the arithmetic is visible.
    if seen:
        first = min(h["ldr"] for h in hits)
        idx = next(i for i, x in enumerate(insns) if x.address == first)
        begin = idx
        # walk back to the prologue
        for k in range(idx, max(0, idx - 300), -1):
            if insns[k].mnemonic == "stp" and "x29" in insns[k].op_str:
                begin = k
                break
        end = min(len(insns), idx + 120)
        print("\n=== function around the HID pool loads ===")
        for k in range(begin, end):
            i = insns[k]
            mark = ""
            for h in hits:
                if i.address == h["ldr"] or i.address == h["adrp"]:
                    mark = "  <== pool 0x%06x" % h["foff"]
            print("0x%x  %-8s %-46s ; %s%s"
                  % (i.address, i.mnemonic, i.op_str, i.bytes.hex(), mark))


if __name__ == "__main__":
    main(sys.argv[1])
