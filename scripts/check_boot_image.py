#!/usr/bin/env python3
"""Check that a boot image carries the kernel we expect.

    check_boot_image.py BOOT.img [--need MARK] [--need MARK] ...

The image is a FAT volume with the EFI payload inside it, so the kernel
strings are split across cluster boundaries and `strings(1)` misses them.
This walks the raw bytes instead.

--need takes a literal byte string, for example:

    check_boot_image.py TEST_Z_0111.img --need 'gui=%d'
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--need", action="append", default=[],
                    help="a literal byte string the image must contain")
    args = ap.parse_args()

    try:
        data = open(args.image, "rb").read()
    except OSError as e:
        print("cannot read %s: %s" % (args.image, e), file=sys.stderr)
        return 2

    if not args.need:
        print("%s: %d bytes" % (args.image, len(data)))
        return 0

    missing = [m for m in args.need if m.encode() not in data]
    for m in args.need:
        n = data.count(m.encode())
        print("   %r: %d" % (m, n))
    if missing:
        print("%s: MISSING %s" % (args.image, ", ".join(missing)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
