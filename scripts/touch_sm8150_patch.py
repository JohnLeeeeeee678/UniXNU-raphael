"""Compute and verify the instruction encodings for the SM8150 touch fix.

The 0060 touch driver was written for the sweet platform, which is a
SM7150.  The raphael is a SM8150, so the GCC votes, the root clock
generator and the GENI serial engine all live somewhere else.

Everything that has to change is an immediate field inside an existing
instruction, so no branch moves and no code grows.  This script derives
the new encodings and checks them with capstone before they are applied.
"""

import struct
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

MD = Cs(CS_ARCH_ARM64, CS_MODE_ARM)


def movz(w, imm16, hw=0):
    """MOVZ 32 bit: sf opc 100101 hw imm16 Rd.

    hw is the two bit shift field, one means a left shift by sixteen.
    """
    assert 0 <= imm16 <= 0xFFFF
    assert hw in (0, 1)
    return 0x52800000 | (hw << 21) | (imm16 << 5) | w


def movk(w, imm16, hw=1):
    assert 0 <= imm16 <= 0xFFFF
    assert hw in (0, 1)
    return 0x72800000 | (hw << 21) | (imm16 << 5) | w


def add_imm_shifted(xd, xn, imm12, lsl12=True):
    """ADD (immediate, shifted register) 64 bit: sf op S 100010 sh imm12 Rn Rd.

    sh is a single bit, one means a left shift by twelve.
    """
    assert 0 <= imm12 <= 0xFFF
    return 0x91000000 | ((1 if lsl12 else 0) << 22) | (imm12 << 10) \
        | (xn << 5) | xd


def sub_imm(xd, xn, imm12):
    """SUB (immediate) 64 bit: sf 1 0 100010 sh imm12 Rn Rd."""
    assert 0 <= imm12 <= 0xFFF
    return 0xD1000000 | (imm12 << 10) | (xn << 5) | xd


def show(word):
    for ins in MD.disasm(struct.pack("<I", word), 0x1000):
        return "%s %s" % (ins.mnemonic, ins.op_str)
    return "?"


# (file offset, label, old word, new word)
PATCHES = [
    # The GENI serial engine of the touch controller.  The sweet platform
    # has it on SE7 at 0xa84000, the raphael has it on SE19 at 0xc88000.
    (0x4E62F4, "touch-se-base",
     add_imm_shifted(0, 19, 0xA2A), add_imm_shifted(0, 19, 0xC2E)),

    # The root clock generator of the wrapper.  wrapper1 S1 on the sweet
    # platform, wrapper2 S2 on the raphael.
    (0x4E6318, "touch-rcg",
     movz(21, 0x8148), movz(21, 0xE3A8)),

    # The clock vote register.  wrapper1 on the sweet platform, wrapper2
    # on the raphael.
    (0x4E6320, "touch-vote-register",
     movz(9, 0x200C), movz(9, 0x2014)),

    # The vote mask.  The sweet platform votes for the wrapper1 clocks,
    # the raphael needs the wrapper2 master AHB, slave AHB and S2 clock.
    (0x4E6330, "touch-vote-mask",
     movz(11, 0xBC, hw=1), movz(11, 0x46)),

    # The branch register that is reported when the clock does not come
    # up, printed as the first element of the branches array.
    (0x4E6458, "touch-branch-report",
     movz(22, 0x8004), movz(22, 0xE3A4)),

    # The five branch checks all look at the same register now, the one
    # that really carries the S2 clock.
    (0x4E6464, "touch-branch-0",
     sub_imm(24, 21, 0x144), sub_imm(24, 21, 0x4)),
    (0x4E6478, "touch-branch-1",
     sub_imm(24, 21, 0x140), sub_imm(24, 21, 0x4)),
    (0x4E648C, "touch-branch-2",
     sub_imm(24, 21, 0x13C), sub_imm(24, 21, 0x4)),
    (0x4E64A0, "touch-branch-3",
     sub_imm(24, 21, 0x138), sub_imm(24, 21, 0x4)),
]


def main():
    path = sys.argv[1]
    data = open(path, "rb").read()
    ok = True
    for off, label, old, new in PATCHES:
        actual = struct.unpack_from("<I", data, off)[0]
        mark = "ok " if actual == old else "BAD"
        if actual != old:
            ok = False
        print("%s 0x%06x %-22s old=%08x (%s)  new=%08x (%s)" % (
            mark, off, label, actual, show(actual), new, show(new)))
    print("\nall expected bytes match" if ok else "\nMISMATCH")


if __name__ == "__main__":
    main()
