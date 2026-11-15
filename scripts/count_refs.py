"""Count code references to a constant in the kernel's __TEXT,__const pool."""
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, "scripts")
from find_edge_const import load_commands  # noqa: E402


def main(path, vm_hex):
    data = open(path, "rb").read()
    segs = load_commands(data)
    target = int(vm_hex, 16)
    page = target & ~0xFFF
    lo12 = target & 0xFFF

    text = None
    for s in segs:
        for x in s["sections"]:
            if x["name"] == "__text" and x["size"]:
                if text is None or x["size"] > text["size"]:
                    text = x
    base, off, size = text["addr"], text["offset"], text["size"]
    code = data[off:off + size]

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True

    hits = []
    pending = {}
    for ins in md.disasm(code, base):
        if ins.mnemonic == ".byte":
            continue
        if ins.mnemonic == "adrp":
            if (ins.operands[1].imm & 0xFFFFFFFFFFFFFFFF) == page:
                pending[ins.operands[0].reg] = ins.address
            continue
        if ins.mnemonic == "add" and len(ins.operands) == 3:
            dst, src, imm = ins.operands
            if imm.type == 2 and imm.imm == lo12 and dst.reg == src.reg:
                if dst.reg in pending:
                    hits.append((pending[dst.reg], ins.address))
                    del pending[dst.reg]
    print("target 0x%x: %d code references" % (target, len(hits)))
    for a, b in hits:
        print("   adrp 0x%x  add 0x%x" % (a, b))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
