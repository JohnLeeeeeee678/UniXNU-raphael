"""Disassemble a window of the kernel around a virtual address."""
import struct
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, "D:/raphael-ios/work")
from find_edge_const import load_commands  # noqa: E402


def main(path, vaddr, before=40, after=40):
    data = open(path, "rb").read()
    segments = load_commands(data)
    text = None
    for s in segments:
        for x in s["sections"]:
            if x["name"] == "__text" and x["size"]:
                if text is None or x["size"] > text["size"]:
                    text = x
    base = text["addr"]
    off = text["offset"]
    size = text["size"]

    start_va = vaddr - before * 4
    end_va = vaddr + after * 4
    start_off = off + (start_va - base)
    code = data[start_off:off + (end_va - base)]

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for ins in md.disasm(code, start_va):
        mark = " <<<<<" if ins.address == vaddr else ""
        fo = off + (ins.address - base)
        print("0x%x  (file 0x%x)  %-8s %-34s%s" % (
            ins.address, fo, ins.mnemonic, ins.op_str, mark))


if __name__ == "__main__":
    path = sys.argv[1]
    va = int(sys.argv[2], 16)
    b = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    a = int(sys.argv[4]) if len(sys.argv) > 4 else 40
    main(path, va, b, a)
