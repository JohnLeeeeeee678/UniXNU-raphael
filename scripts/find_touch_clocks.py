"""Locate the touch clock helper in the kernel binary.

The 0060 driver polls the GCC branch registers and gives up when the
CLK_OFF bit is still set.  On the raphael panel one of those branches
runs in hardware clock gating mode, where that bit has a different
meaning, so the driver bails out before it ever votes for the touch
power rail.

The helper is found through the printf that reports the failure, then
the surrounding instructions are disassembled so the exact instruction
that builds the mask can be looked at.
"""

import struct
import sys

import capstone

from find_edge_const import load_commands

BRANCH_STR = b"SWEET TOUCH: GCC branch %#x halted (%#x)"


def text_section(secs):
    """Pick the real __text, the loader can list a placeholder first."""
    best = None
    for seg in load_commands(open(sys.argv[1], "rb").read()):
        for sec in seg["sections"]:
            if sec["name"] == "__text" and sec["size"] > 0:
                if best is None or sec["size"] > best["size"]:
                    best = sec
    return best


def va_to_file(data, va):
    for seg in load_commands(data):
        for sec in seg["sections"]:
            if sec["addr"] <= va < sec["addr"] + sec["size"]:
                return sec["offset"] + (va - sec["addr"])
    return None


def main():
    path = sys.argv[1]
    data = open(path, "rb").read()
    text = text_section(None)
    if text is None:
        raise SystemExit("no __text")
    print("__text addr=0x%x off=0x%x size=0x%x" % (
        text["addr"], text["offset"], text["size"]))

    i = data.find(BRANCH_STR)
    if i < 0:
        raise SystemExit("string not found")
    # The file offset of a string maps back through the segment table.
    va = None
    for seg in load_commands(data):
        if seg["fileoff"] <= i < seg["fileoff"] + seg["filesize"]:
            va = seg["vmaddr"] + (i - seg["fileoff"])
            break
    if va is None:
        raise SystemExit("cannot map string to a VA")
    print("string file=0x%x VA=0x%x" % (i, va))

    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.skipdata = False
    code = data[text["offset"]:text["offset"] + text["size"]]

    page = va & ~0xFFF
    lo12 = va & 0xFFF
    print("page=0x%x lo12=0x%x" % (page, lo12))

    # Scan the raw bytes for the ADRP encoding: the text section holds
    # inline data as well, so a linear disassembly stops early.
    hits = []
    for off in range(text["offset"], text["offset"] + text["size"] - 4, 4):
        word = struct.unpack_from("<I", data, off)[0]
        if word & 0x9F000000 != 0x90000000:
            continue
        immlo = (word >> 29) & 0x3
        immhi = (word >> 5) & 0x7FFFF
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= 1 << 21
        pc = text["addr"] + (off - text["offset"])
        target_page = (pc & ~0xFFF) + (imm << 12)
        if target_page == page:
            hits.append(pc)
    print("adrp for page 0x%x: %d candidates" % (page, len(hits)))

    # The string address is formed by adrp + add with the low 12 bits.
    # Scan the whole text section for that add and then check whether the
    # instruction before it is the matching adrp.
    refs = []
    for off in range(text["offset"], text["offset"] + text["size"] - 24, 4):
        w = struct.unpack_from("<I", data, off)[0]
        if w & 0xFF800000 != 0x91000000:
            continue
        if (w >> 10) & 0xFFF != lo12:
            continue
        pc = text["addr"] + (off - text["offset"])
        for back in range(1, 6):
            prev_off = off - 4 * back
            p = struct.unpack_from("<I", data, prev_off)[0]
            if p & 0x9F000000 != 0x90000000:
                continue
            immlo = (p >> 29) & 0x3
            immhi = (p >> 5) & 0x7FFFF
            imm = (immhi << 2) | immlo
            if imm & (1 << 20):
                imm -= 1 << 21
            ppc = text["addr"] + (prev_off - text["offset"])
            if ((ppc & ~0xFFF) + (imm << 12)) == page:
                refs.append((ppc, pc))
            break
    print("string refs:", [("0x%x" % r[0], "0x%x" % r[1]) for r in refs])

    target = None
    for r in refs:
        target = r[0]
        break

    if target is None:
        raise SystemExit("no exact reference found")
    print("\n=== block around 0x%x ===" % target)
    start = target - 0x100
    for ins in md.disasm(data[start:start + 0x400], start):
        mark = ""
        if ins.address == target:
            mark = "   <<< string ref"
        print("0x%x  %-10s %s%s" % (
            ins.address, ins.mnemonic, ins.op_str, mark))


if __name__ == "__main__":
    main()
