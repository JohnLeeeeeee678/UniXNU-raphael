"""Find the SWEET HID touch function and the edge-tip comparison in it.

Strategy: locate the IOLog format string, find every adrp/add pair in __text
that materialises its address, and disassemble the enclosing function.
"""
import struct
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, "D:/raphael-ios/work")
from find_edge_const import load_commands  # noqa: E402


def text_section(segments):
    best = None
    for s in segments:
        for x in s["sections"]:
            if x["name"] == "__text" and x["size"]:
                if best is None or x["size"] > best["size"]:
                    best = x
    return best


def find_string_va(data, segments, needle):
    idx = data.find(needle)
    if idx < 0:
        return None, None
    for s in segments:
        if s["fileoff"] <= idx < s["fileoff"] + s["filesize"]:
            return idx, s["vmaddr"] + (idx - s["fileoff"])
    return idx, None


def main(path):
    data = open(path, "rb").read()
    segments = load_commands(data)
    text = text_section(segments)
    base, off, size = text["addr"], text["offset"], text["size"]
    code = data[off:off + size]

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    insns = [i for i in md.disasm(code, base) if i.mnemonic != ".byte"]
    print("__text 0x%x..0x%x  %d instructions" % (base, base + size, len(insns)))
    index = {ins.address: i for i, ins in enumerate(insns)}

    needle = sys.argv[2].encode() if len(sys.argv) > 2 else b"SWEET HID: touch %d %s at %d,%d%s"
    idx, sva = find_string_va(data, segments, needle)
    print("string file 0x%x vm 0x%x" % (idx, sva))
    page = sva & ~0xFFF
    lo12 = sva & 0xFFF

    # Find adrp instructions pointing at the page of the string.
    refs = []
    for i, ins in enumerate(insns):
        if ins.mnemonic != "adrp":
            continue
        op = ins.operands[1]
        if op.type != 2:
            continue
        target = op.imm & 0xFFFFFFFFFFFFFFFF
        if target != page:
            continue
        # Look ahead for an add with the matching low 12 bits.
        for j in range(i + 1, min(i + 6, len(insns))):
            nxt = insns[j]
            if nxt.mnemonic == "add" and nxt.operands[2].type == 2 \
                    and nxt.operands[2].imm == lo12 and nxt.operands[0].reg == ins.operands[0].reg:
                refs.append((i, j))
                break
    print("string references: %d" % len(refs))

    for i, j in refs:
        print("\n=== reference at 0x%x (add at 0x%x) ===" % (
            insns[i].address, insns[j].address))
        # Walk backwards to the function prologue: look for the stp of x29/x30.
        start = i
        for k in range(i, max(0, i - 400), -1):
            mn = insns[k].mnemonic
            if mn == "stp" and "x29" in insns[k].op_str and "x30" in insns[k].op_str:
                start = k
                break
        # Walk forward to the ret.
        end = j
        for k in range(j, min(len(insns), j + 600)):
            if insns[k].mnemonic == "ret":
                end = k
                break
        print("function 0x%x..0x%x  (%d instructions)" % (
            insns[start].address, insns[end].address, end - start + 1))
        for k in range(start, end + 1):
            ins = insns[k]
            note = ""
            for op in ins.operands:
                if op.type == 2 and op.imm in (2351, 1031, 2399, 1079, 48, 2340, 2400, 2436,
                                               1080, 1125, 2436, 2291, 2276):
                    note = "   ;<< imm %d" % op.imm
            print("  0x%x  %-8s %-40s%s" % (
                ins.address, ins.mnemonic, ins.op_str, note))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "D:/raphael-ios/work/kernel_0111.macho")
