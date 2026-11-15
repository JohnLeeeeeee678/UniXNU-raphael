#!/usr/bin/env python3
"""Patch the SWEET digitizer edge threshold inside a UniXNU boot image.

The 0071 patch computes the digitizer edge tip from the raw panel
coordinates with the panel height hard coded for the 1080x2400 guacamole
screen:

    fEdge[finger] = x < 48 || x > 1079 - 48 ||
                    y < 48 || y > 2399 - 48;

On the Redmi K20 Pro (raphael) the panel is 1080x2340, so "y > 2351" can
never be true and the digitizer never reports kIOHIDDigitizerEventFromEdgeTip.
UIKit derives the edge type from that bit, so the swipe-up unlock and the
home gesture are impossible.

The threshold is a plain MOVZ immediate in the compiled kernel, so the fix
is a four byte patch: 2351 becomes 2339 - 48 = 2291.  The kernel carries no
code signature blob, so nothing has to be re-signed.

Usage:
    patch_kernel.py IMAGE [--out NEWIMAGE] [--verify]
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootimg_args import ramdisk_range  # noqa: E402
from fat_args import Fat32  # noqa: E402

KERNEL_PATH = "EFI/UNIXNU/PAYLOADS/KERNEL~1MAC"

# (name, offset in the Mach-O file, expected bytes, replacement bytes, why)
PATCHES = [
    (
        "edge-tip-threshold",
        0xA6B948,
        struct.pack("<I", 0x528125E8),   # mov w8, #0x92f   (2399 - 48)
        struct.pack("<I", 0x52811E68),   # mov w8, #0x8f3   (2339 - 48)
        "digitizer edge tip threshold 2351 -> 2291 for the 1080x2340 panel",
    ),
]

# Multi word patches: (name, offset, expected words, replacement words, why)
#
# usb-status-direction is the binary form of 0112-sweet-usb-status-direction.
# 0101 queued the status stage of a control transfer on the endpoint number
# that came with the "control status" event, which is not the direction the
# host is waiting for.  Windows opens a CDC-ACM port with SET_LINE_CODING -
# a control OUT transfer with a seven byte data stage - and then waits for
# an IN status, so the device answered with an OUT status and the host gave
# up ("the semaphore timeout period has expired", error 121).
#
# The direction is taken from the data stage instead, the same way Linux
# does it in drivers/usb/dwc3/ep0.c:
#
#     direction = !dwc->ep0_expect_in;        /* ep0_expect_in = setup dir */
#
# The setup direction bit lives in ud.data_in (ud + 0x1c, written in
# ud_setup() from bmRequestType bit 7), so
#
#     sep = !ud.data_in
#
# is the direction of the status stage: IN after an OUT data stage or after
# a transfer without a data stage, OUT after an IN data stage.
#
# sep drives two things:
#
#   * the TRB slot     UD_TRB_IN (0x1010) for an IN status, UD_TRB_OUT
#                      (0x1000) for an OUT status
#   * the DWC3 channel channel 1 (DEPCMD(1)) for an IN status, channel 0
#                      (DEPCMD(0)) for an OUT status
#
# The TRB *control* field is left alone.  TRBCTL_STATUS2 (0xc33) and
# TRBCTL_STATUS3 (0xc43) are not directions: in Linux they are selected by
# the hardware's three_stage_setup flag, and the direction comes from the
# endpoint the status TRB is queued on:
#
#     type = dwc->three_stage_setup ? TRBCTL_CONTROL_STATUS3
#                                    : TRBCTL_CONTROL_STATUS2;
#     dwc3_ep0_prepare_one_trb(dep, ..., type);
#     dwc3_ep0_start_trans(dep);            /* dep->number = direction */
#
# The two cases that already worked keep their behaviour: SET_CONFIGURATION
# (no data stage) stays on channel 1, GET_DESCRIPTOR (IN data) stays on
# channel 0.  Only SET_LINE_CODING changes.
#
# The replacement is 27 instructions long, the same as the original block:
# the three word write of the TRB buffer address (str w10 / lsr / str w10)
# is folded into a single 64 bit store, which frees the two slots that the
# "cmp w23, #0" on the event endpoint number used to occupy.
USB_STATUS_ORIG = [
    0x710002FF, 0x52820009, 0x5282020A, 0x9A8A0138, 0xA9402B49, 0x8B180129,
    0x5282200B, 0x8B0B014A, 0xB900012A, 0xD360FD4A, 0xB900052A, 0xB900093F,
    0x71000D1F, 0x52818668, 0x5281886A, 0x1A880148, 0xB9000D28, 0xF9400748,
    0x8B180100, 0x52800201, 0x52800022, 0x97FE39C8, 0xF9400748, 0x8B180103,
    0xD360FC62, 0xAA1703E0, 0x17FFFF74,
]

USB_STATUS_NEW = [
    0x39407357,  # +0   ldrb w23, [x26, #0x1c]   ud.data_in
    0x520002F7,  # +4   eor  w23, w23, #1        sep = !data_in
    0x710002FF,  # +8   cmp  w23, #0             Z = (sep == 0)
    0x52820009,  # +12  mov  w9, #0x1000         UD_TRB_OUT
    0x5282020A,  # +16  mov  w10, #0x1010        UD_TRB_IN
    0x9A891158,  # +20  csel x24, x10, x9, ne    slot = sep ? IN : OUT
    0xA9402B49,  # +24  ldp  x9, x10, [x26]      dma, dma_pa
    0x8B180129,  # +28  add  x9, x9, x24         TRB virtual address
    0x5282200B,  # +32  mov  w11, #0x1100        UD_DATA
    0x8B0B014A,  # +36  add  x10, x10, x11       buffer physical address
    0xF900012A,  # +40  str  x10, [x9]           trb->ptr (8 bytes)
    0xB900093F,  # +44  str  wzr, [x9, #8]       trb->len = 0
    0x71000D1F,  # +48  cmp  w8, #3              ud.state (unchanged)
    0x52818668,  # +52  mov  w8, #0xc33          TRBCTL_STATUS2
    0x5281886A,  # +56  mov  w10, #0xc43         TRBCTL_STATUS3
    0x1A880148,  # +60  csel w8, w10, w8, eq     ctl (unchanged)
    0xB9000D28,  # +64  str  w8, [x9, #0xc]      trb->ctl
    0xF9400748,  # +68  ldr  x8, [x26, #8]       dma_pa
    0x8B180100,  # +72  add  x0, x8, x24         flush address
    0x52800201,  # +76  mov  w1, #0x10
    0x52800022,  # +80  mov  w2, #1
    0x97FE39C8,  # +84  bl   flush_dcache64
    0xF9400748,  # +88  ldr  x8, [x26, #8]       dma_pa
    0x8B180103,  # +92  add  x3, x8, x24         TRB physical address
    0xD360FC62,  # +96  lsr  x2, x3, #0x20       address high word
    0xAA1703E0,  # +100 mov  x0, x23             channel = sep
    0x17FFFF74,  # +104 b    ud_epcmd tail
]

PATCHES_BLOCKS = [
    (
        "usb-status-direction",
        0x4EB6D8,
        USB_STATUS_ORIG,
        USB_STATUS_NEW,
        "control transfer status stage direction from the data stage, not "
        "from the event endpoint number (0112)",
    ),
]

# Data patches inside __TEXT,__const: (name, offset, expected, replacement, why)
#
# touch-panel-height is the binary form of the 0061 panel height fix.
#
# 0061 presents the display as the iPhone X panel: 1125x2436 logical, with
# the physical panel centred inside it.  SweetFramebuffer knows the real
# panel size (it reads it from the device tree) and computes
#
#     fOffX = (fLogicalW - fWidth) / 2
#     fOffY = (fLogicalH - fHeight) / 2
#
# which on the 1080x2340 raphael panel gives (22, 48).
#
# SweetHID cannot know the panel size, so 0061 hard coded the 2400 of the
# guacamole panel:
#
#     fLogicalH = native ? 2400 : 2436;
#     fOffX = (fLogicalW - 1080) / 2;
#     fOffY = (fLogicalH - 2400) / 2;      /* 18 on raphael */
#
# The digitizer and the framebuffer therefore disagree by 30 logical pixels
# in Y: every touch lands 30 points above the finger, and the swipe up from
# the bottom edge never reaches the home indicator.
#
# The compiler turned the two offsets into one vector expression.  In
# SweetHID::start (file 0x28ae0) it reads:
#
#     mask = (sweetfb_native == 0) ? ~0 : 0;
#     bsl  v0, v2, v1;              /* pick the logical size */
#     add  v1.2s, v0.2s, v1.2s;     /* + (200, 160) */
#     ushr v1.2s, v1.2s, #1;        /* >> 1 */
#     and  v1.8b, v1.8b, v2.8b;     /* & (126, 114) */
#
# The addend is not a plain negation: the compiler folds the subtraction
# into a shift with a bias C, so
#
#     addend = 2 * C - native
#
# with C = 1280 in the Y lane (640 in the X lane).  The mask B clears C
# again, because C only has bits above bit 6:
#
#     ((2436 + 160) >> 1) & 114 = 1298 & 114 = 18 = (2436 - 2400) / 2
#     ((2436 + 220) >> 1) & 114 = 1328 & 114 = 48 = (2436 - 2340) / 2
#     ((2340 + 220) >> 1) & 114 = 1280 & 114 =  0 = (2340 - 2340) / 2
#
# So two words have to change, and both of them fold the 2400:
#
#   0x28ae0  (1080, 2400)  the native mode logical size.  In native mode
#                          the panel is presented unscaled, so this has to
#                          be the real raphael panel height 2340 as well.
#   0x28ae8  (200, 160)    the addend, 2 * 1280 - 2400.  For 2340 it
#                          becomes 2 * 1280 - 2340 = 220.
#
# Both words are referenced from SweetHID::start only.  0x28a40, the
# logical size (1125, 2436), is shared with the framebuffer and must not be
# touched.
PATCHES_DATA = [
    (
        "touch-native-logical-height",
        0x28AE4,
        struct.pack("<I", 0x00000960),   # 2400
        struct.pack("<I", 0x00000924),   # 2340
        "SweetHID native mode logical height 2400 -> 2340 (raphael panel)",
    ),
    (
        "touch-offset-panel-height",
        0x28AEC,
        struct.pack("<I", 0x000000A0),   # 160  (= 2 * 1280 - 2400)
        struct.pack("<I", 0x000000DC),   # 220  (= 2 * 1280 - 2340)
        "SweetHID offset expression subtracts 2340 instead of 2400, so "
        "fOffY becomes 48 and matches the framebuffer",
    ),
]


# Instruction level patches: (name, file offset, expected word, new word, why)
#
# The 0060 touch driver was written for the sweet platform, which is a
# SM7150.  The raphael is a SM8150, so the touch controller sits on a
# different GENI serial engine and its clocks live in a different clock
# controller block.
#
# Everything that has to change is an immediate field inside an existing
# instruction, so no branch moves, no code grows and no relocation is
# needed.  The values come from the Linux clock driver for the SM8150
# (drivers/clk/qcom/gcc-sm8150.c) and from the raphael device tree:
#
#   sweet (SM7150)              raphael (SM8150)
#   -------------------------   ------------------------------------
#   SE7   at 0x00a84000         SE19  at 0x00c88000
#   vote  at 0x5200c             vote  at 0x52014
#   mask  bits 18-21, 23         mask  bits 1, 2, 6
#   RCG   0x18148 (wrap1 S1)     RCG   0x1e3a8 (wrap2 S2)
#   branch 0x18004..0x18144      branch 0x1e3a4 (wrap2 S2)
#
# The vote mask covers GCC_QUPV3_WRAP_2_M_AHB_CLK (bit 2),
# GCC_QUPV3_WRAP_2_S_AHB_CLK (bit 1) and GCC_QUPV3_WRAP2_S2_CLK (bit 6),
# which are the three clocks the raphael device tree asks for on the
# qupv3_se19_i2c node.
#
# All five branch checks now look at the same register, the one that
# really carries the S2 clock.  The sweet platform also checked
# 0x18008, which on the SM8150 is the wrapper1 slave AHB clock.  That
# clock runs in hardware clock gating mode there, and Linux skips the
# halt bit entirely in that mode (clk_branch_in_hwcg_mode), so the
# 0060 check was looking at a bit that no longer means what it meant
# on the SM7150.
PATCHES_WORDS = [
    (
        "touch-se-base",
        0x4E62F4,
        0x9168AA60,   # add x0, x19, #0xa2a, lsl #12  -> 0xa84000
        0x9170BA60,   # add x0, x19, #0xc2e, lsl #12  -> 0xc88000
        "touch controller moves from SE7 to SE19",
    ),
    (
        "touch-rcg",
        0x4E6318,
        0x52902915,   # mov w21, #0x18148
        0x529C7515,   # mov w21, #0x1e3a8
        "root clock generator moves from wrapper1 S1 to wrapper2 S2",
    ),
    (
        "touch-vote-register",
        0x4E6320,
        0x52840189,   # mov w9, #0x5200c
        0x52840289,   # mov w9, #0x52014
        "clock vote register moves to the wrapper2 block",
    ),
    (
        "touch-vote-mask",
        0x4E6330,
        0x52A0178B,   # mov w11, #0xbc0000
        0x528008CB,   # mov w11, #0x46
        "vote for the wrapper2 master AHB, slave AHB and S2 clocks",
    ),
    (
        "touch-branch-report",
        0x4E6458,
        0x52900096,   # mov w22, #0x18004
        0x529C7496,   # mov w22, #0x1e3a4
        "the branch that is reported when the clock stays off",
    ),
    (
        "touch-branch-0",
        0x4E6464,
        0xD10512B8,   # sub x24, x21, #0x144
        0xD10012B8,   # sub x24, x21, #4
        "branch check 0 points at the wrapper2 S2 clock",
    ),
    (
        "touch-branch-1",
        0x4E6478,
        0xD10502B8,   # sub x24, x21, #0x140
        0xD10012B8,   # sub x24, x21, #4
        "branch check 1 points at the wrapper2 S2 clock",
    ),
    (
        "touch-branch-2",
        0x4E648C,
        0xD104F2B8,   # sub x24, x21, #0x13c
        0xD10012B8,   # sub x24, x21, #4
        "branch check 2 points at the wrapper2 S2 clock",
    ),
    (
        "touch-branch-3",
        0x4E64A0,
        0xD104E2B8,   # sub x24, x21, #0x138
        0xD10012B8,   # sub x24, x21, #4
        "branch check 3 points at the wrapper2 S2 clock",
    ),
    # The pin controller.  The sweet platform reaches its TLMM through the
    # north bridge at 0x03900000, the raphael has its TLMM at 0x03000000.
    # Reading the wrong address aborts the kernel, which is what happened
    # on the first attempt.
    (
        "touch-tlmm-base",
        0x4E62E8,
        0x52A07200,   # mov w0, #0x3900000
        0x52A06000,   # mov w0, #0x3000000
        "pin controller moves from the north bridge to the real TLMM",
    ),
    # The mapping length has to reach the interrupt pin of the raphael,
    # which is gpio122 at offset 0x7a000.  The old length was 0x5b000,
    # built from the same constant the serial engine base uses.  Adding
    # 0x22000 to that constant gives 0x7c000.
    (
        "touch-tlmm-size",
        0x4E62E4,
        0xB2740261,   # orr x1, x19, #0x1000
        0x91408A61,   # add x1, x19, #0x22, lsl #12
        "pin controller mapping grows to 0x7c000 so gpio122 is reachable",
    ),
]


def patch_macho(macho, only=None):
    for name, off, expect, repl, why in PATCHES:
        if only and name not in only:
            continue
        actual = macho[off:off + 4]
        if actual != expect:
            raise SystemExit(
                f"patch {name}: expected {expect.hex()} at 0x{off:x}, "
                f"found {actual.hex()} -- the kernel layout changed")
        macho[off:off + 4] = repl
        print(f"patched {name} at 0x{off:x}: {expect.hex()} -> {repl.hex()} ({why})")
    for name, off, expect, repl, why in PATCHES_BLOCKS:
        if only and name not in only:
            continue
        size = len(expect) * 4
        actual = list(struct.unpack_from("<%dI" % len(expect), macho, off))
        if actual != expect:
            raise SystemExit(
                f"patch {name}: expected {len(expect)} words at 0x{off:x}, "
                f"found {' '.join('%08x' % w for w in actual)} -- "
                f"the kernel layout changed")
        struct.pack_into("<%dI" % len(repl), macho, off, *repl)
        print(f"patched {name} at 0x{off:x}: {len(repl)} words ({why})")
    for name, off, expect, repl, why in PATCHES_DATA:
        if only and name not in only:
            continue
        actual = bytes(macho[off:off + len(expect)])
        if actual != expect:
            raise SystemExit(
                f"patch {name}: expected {expect.hex()} at 0x{off:x}, "
                f"found {actual.hex()} -- the kernel layout changed")
        macho[off:off + len(repl)] = repl
        print(f"patched {name} at 0x{off:x}: {expect.hex()} -> {repl.hex()} ({why})")
    for name, off, expect, repl, why in PATCHES_WORDS:
        if only and name not in only:
            continue
        actual = struct.unpack_from("<I", macho, off)[0]
        if actual != expect:
            raise SystemExit(
                f"patch {name}: expected {expect:08x} at 0x{off:x}, "
                f"found {actual:08x} -- the kernel layout changed")
        struct.pack_into("<I", macho, off, repl)
        print(f"patched {name} at 0x{off:x}: {expect:08x} -> {repl:08x} ({why})")
    return macho


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out")
    ap.add_argument("--only", help="comma separated patch names to apply")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None

    image = bytearray(Path(args.image).read_bytes())
    offset, size = ramdisk_range(image)
    fat = Fat32(bytes(image[offset:offset + size]))
    _, cluster, fsize = fat.find(KERNEL_PATH)
    macho = bytearray(fat.read_chain(cluster, fsize))
    print(f"kernel.macho: {fsize} bytes")

    patch_macho(macho, only)

    payload, _ = fat.write_file(KERNEL_PATH, bytes(macho))
    image[offset:offset + size] = payload

    out = Path(args.out) if args.out else Path(args.image)
    out.write_bytes(image)
    print(f"wrote {out}")

    if args.verify:
        image2 = bytearray(out.read_bytes())
        offset2, size2 = ramdisk_range(image2)
        fat2 = Fat32(bytes(image2[offset2:offset2 + size2]))
        _, cluster2, fsize2 = fat2.find(KERNEL_PATH)
        blob = fat2.read_chain(cluster2, fsize2)
        ok = True
        for name, off, expect, repl, why in PATCHES:
            got = blob[off:off + 4]
            state = "OK" if got == repl else "MISMATCH"
            if got != repl:
                ok = False
            print(f"verify {name}: {got.hex()} {state}")
        for name, off, expect, repl, why in PATCHES_BLOCKS:
            got = list(struct.unpack_from("<%dI" % len(repl), blob, off))
            state = "OK" if got == repl else "MISMATCH"
            if got != repl:
                ok = False
            print(f"verify {name}: {len(repl)} words {state}")
        for name, off, expect, repl, why in PATCHES_DATA:
            got = bytes(blob[off:off + len(repl)])
            state = "OK" if got == repl else "MISMATCH"
            if got != repl:
                ok = False
            print(f"verify {name}: {got.hex()} {state}")
        for name, off, expect, repl, why in PATCHES_WORDS:
            got = struct.unpack_from("<I", blob, off)[0]
            state = "OK" if got == repl else "MISMATCH"
            if got != repl:
                ok = False
            print(f"verify {name}: {got:08x} {state}")
        # The payload must be byte identical apart from the patched words.
        diff = [i for i in range(fsize2) if blob[i] != macho[i]]
        print("changed bytes in kernel.macho:", len(diff))
        if not ok:
            raise SystemExit("verification failed")


if __name__ == "__main__":
    main()
