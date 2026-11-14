#!/usr/bin/env python3
"""Rewrite the kernel boot arguments inside an Aloha boot image.

The boot image is an Android boot image whose ramdisk is the UniXNU payload
-- a FAT32 volume -- and the kernel arguments live in EFI/UNIXNU/unixnu.toml
on that volume.  Editing them therefore needs neither a kernel rebuild nor a
firmware rebuild: the image is copied, the FAT file is rewritten in place and
the result is a bootable image with different kernel arguments.

Only the arguments change; the kernel, the device tree and the firmware are
carried over byte for byte.

Usage:
    bootimg_args.py show  IMAGE
    bootimg_args.py set   IMAGE "arg1 arg2 ..."
    bootimg_args.py patch IMAGE "name=value"          # add/replace one arg
    bootimg_args.py patch IMAGE "name=value" --out NEWIMAGE
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fat_args import Fat32, TOML_PATH  # noqa: E402


def ramdisk_range(image):
    """Return (offset, size) of the payload inside an Android boot image."""
    if image[:8] != b"ANDROID!":
        raise SystemExit("not an Android boot image")
    kernel_size = struct.unpack_from("<I", image, 8)[0]
    ramdisk_size = struct.unpack_from("<I", image, 16)[0]
    page_size = struct.unpack_from("<I", image, 36)[0]
    if not page_size:
        page_size = 2048
    kernel_off = ((1632 + page_size - 1) // page_size) * page_size
    ramdisk_off = kernel_off + ((kernel_size + page_size - 1) // page_size) * page_size
    return ramdisk_off, ramdisk_size


def read_args(image):
    offset, size = ramdisk_range(image)
    fat = Fat32(bytes(image[offset:offset + size]))
    _, cluster, fsize = fat.find(TOML_PATH)
    blob = fat.read_chain(cluster, fsize).decode("latin-1")
    for line in blob.splitlines():
        if line.startswith("args = "):
            return line[len("args = "):].strip().strip('"')
    raise SystemExit("no args line in unixnu.toml")


def write_args(image, newargs):
    offset, size = ramdisk_range(image)
    fat = Fat32(bytes(image[offset:offset + size]))
    _, cluster, fsize = fat.find(TOML_PATH)
    blob = fat.read_chain(cluster, fsize).decode("latin-1")
    out = []
    hit = False
    for line in blob.splitlines(keepends=True):
        if line.startswith("args = "):
            out.append(f'args = "{newargs}"\n')
            hit = True
        else:
            out.append(line if line.endswith("\n") else line + "\n")
    if not hit:
        raise SystemExit("no args line in unixnu.toml")
    newblob = "".join(out).encode("latin-1")
    payload, _ = fat.write_file(TOML_PATH, newblob)
    image[offset:offset + size] = payload
    return image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["show", "set", "patch"])
    ap.add_argument("image")
    ap.add_argument("args", nargs="?")
    ap.add_argument("--out")
    args = ap.parse_args()

    image = bytearray(Path(args.image).read_bytes())
    if args.command == "show":
        print(read_args(image))
        return
    if args.command == "set":
        newargs = args.args
    else:
        cur = read_args(image).split()
        name = args.args.split("=", 1)[0]
        cur = [a for a in cur if a.split("=", 1)[0] != name]
        cur.append(args.args)
        newargs = " ".join(cur)
    write_args(image, newargs)
    out = Path(args.out) if args.out else Path(args.image)
    out.write_bytes(image)
    print(f"wrote {out}")
    print("args now: " + read_args(bytearray(out.read_bytes())))


if __name__ == "__main__":
    main()
