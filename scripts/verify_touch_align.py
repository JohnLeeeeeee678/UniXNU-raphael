#!/usr/bin/env python3
"""Simulate the SweetHID offset expression exactly as the kernel runs it.

The offset that SweetHID applies to the digitizer coordinates is computed by
four SIMD instructions in SweetHID::start:

    mask = (sweetfb_native == 0) ? ~0 : 0;
    bsl  v0, v2, v1;              /* v0 = mask ? logical : native  */
    add  v1.2s, v0.2s, v1.2s;     /* v1 = v0 + addend              */
    ushr v1.2s, v1.2s, #1;        /* v1 = v1 >> 1                 */
    and  v1.8b, v1.8b, v2.8b;     /* v1 = v1 & mask               */

This tool replays those instructions on the constant pool values that are
actually stored in the kernel, and compares the result with the offset the
framebuffer computes from the real panel size.  Both sides must agree, or
every touch lands in the wrong place.

Usage:
    verify_touch_align.py KERNEL_MACHO [--panel 1080x2340]
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Constant pool offsets of the SweetHID::start constant pool.
POOL_LOGICAL = 0x28A40     # (1125, 2436) - shared with the framebuffer
POOL_NATIVE = 0x28AE0      # (1080, 2400) - native mode logical size
POOL_ADDEND = 0x28AE8      # (200, 160)   - the addend
POOL_MASK = 0x28AF0        # (126, 114)   - the mask


def s32(v):
    return v - 0x100000000 if v >= 0x80000000 else v


def u32(v):
    return v & 0xFFFFFFFF


def sim(data, native_bootarg):
    """Replay the four SIMD instructions on the stored pool values."""
    logical = struct.unpack_from("<2i", data, POOL_LOGICAL)
    native = struct.unpack_from("<2i", data, POOL_NATIVE)
    addend = struct.unpack_from("<2i", data, POOL_ADDEND)
    mask = struct.unpack_from("<2I", data, POOL_MASK)

    # dup v0.2s, w8 / shl #0x1f / cmlt #0
    w8 = 1 if native_bootarg == 0 else 0
    v0 = [u32(w8 << 31)] * 2
    # cmlt v0.2s, v0.2s, #0 -> all ones when the shifted value is negative
    v0 = [0xFFFFFFFF if s32(x) < 0 else 0 for x in v0]

    # bsl v0.8b, v2.8b, v1.8b:  v0 = mask ? v2 : v1  (per 32 bit lane)
    v2 = [u32(x) for x in logical]
    v1_sel = [u32(x) for x in native]
    v0 = [v2[i] if v0[i] == 0xFFFFFFFF else v1_sel[i] for i in range(2)]

    # add v1.2s, v0.2s, v1.2s   (the addend is a signed 32 bit pair)
    v1 = [u32(v0[i] + addend[i]) for i in range(2)]

    # ushr v1.2s, v1.2s, #1
    v1 = [x >> 1 for x in v1]

    # and v1.8b, v1.8b, v2.8b   (the mask is a 64 bit value, two lanes)
    v1 = [v1[i] & mask[i] for i in range(2)]

    return {
        "selected": [s32(x) for x in v0],
        "offset": [s32(x) for x in v1],
    }


def fb_offset(logical, panel_w, panel_h):
    """What SweetFramebuffer computes: (logical - real panel) / 2."""
    return ((logical[0] - panel_w) // 2, (logical[1] - panel_h) // 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel")
    ap.add_argument("--panel", default="1080x2340")
    args = ap.parse_args()

    w, h = (int(x) for x in args.panel.lower().split("x"))
    data = Path(args.kernel).read_bytes()

    logical = struct.unpack_from("<2i", data, POOL_LOGICAL)
    native = struct.unpack_from("<2i", data, POOL_NATIVE)
    addend = struct.unpack_from("<2i", data, POOL_ADDEND)
    mask = struct.unpack_from("<2i", data, POOL_MASK)

    print("kernel: %s" % args.kernel)
    print("panel:  %dx%d" % (w, h))
    print("pool:   logical=%s native=%s addend=%s mask=%s"
          % (logical, native, addend, mask))
    print()

    ok = True
    for label, arg in (("sweetfb_native unset (iPhone X)", 0),
                       ("sweetfb_native=1 (native)", 1)):
        r = sim(data, arg)
        hid = r["offset"]
        fb = fb_offset(r["selected"], w, h)
        same = tuple(hid) == tuple(fb)
        ok = ok and same
        print("%-30s selected=%-12s HID offset=%-10s FB offset=%-10s %s"
              % (label, r["selected"], hid, fb,
                 "MATCH" if same else "MISMATCH"))

    print()
    print("RESULT:", "PASS - touch and display agree" if ok
          else "FAIL - the digitizer is offset from the display")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
