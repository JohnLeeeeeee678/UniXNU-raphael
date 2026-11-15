"""Diagnose how __TEXT,__cstring literals are referenced from __text."""
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, "scripts")
from find_edge_const import load_commands  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else "D:/raphael-ios/work/kernel_0111.macho"
data = open(path, "rb").read()
segs = load_commands(data)

text = None
for s in segs:
    for x in s["sections"]:
        if x["name"] == "__text" and x["size"]:
            if text is None or x["size"] > text["size"]:
                text = x
cstr = None
for s in segs:
    for x in s["sections"]:
        if x["name"] == "__cstring" and x["seg"] == "__TEXT":
            cstr = x

base, off, size = text["addr"], text["offset"], text["size"]
code = data[off:off + size]
lo, hi = cstr["addr"], cstr["addr"] + cstr["size"]
print("__text 0x%x  cstring 0x%x..0x%x" % (base, lo, hi))

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True
md.skipdata = True

n_adrp = 0
n_in = 0
samples = []
for ins in md.disasm(code, base):
    if ins.mnemonic == ".byte":
        continue
    if ins.mnemonic == "adrp":
        n_adrp += 1
        t = ins.operands[1].imm
        if lo <= t < hi:
            n_in += 1
            if len(samples) < 8:
                samples.append((hex(ins.address), ins.op_str, hex(t)))
print("adrp total %d, targeting cstring range %d" % (n_adrp, n_in))
for s in samples:
    print("   ", s)

# What does the very first adrp look like?
md2 = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md2.detail = True
md2.skipdata = True
cnt = 0
for ins in md2.disasm(code, base):
    if ins.mnemonic == "adrp":
        print("first adrp:", hex(ins.address), ins.op_str,
              "ops:", [(o.type, o.imm if o.type == 2 else o.reg) for o in ins.operands])
        cnt += 1
        if cnt >= 3:
            break
