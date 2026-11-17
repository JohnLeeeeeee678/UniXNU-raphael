#!/usr/bin/env python3
"""Unpack an Android boot image (v0/v1/v2) and dump its device tree.

Usage: python tools/unpack_boot.py boot.img outdir
Writes outdir/kernel, outdir/ramdisk (if any), outdir/dtb-table.bin and a
JSON summary outdir/boot.json.
"""
import json
import struct
import sys
from pathlib import Path

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
TOK_BEGIN, TOK_END_NODE, TOK_PROP, TOK_NOP, TOK_END = 1, 2, 3, 4, 9


def align(value, page):
    return (value + page - 1) & ~(page - 1)


def parse_header(data):
    h = {}
    h["magic"] = data[0:8].decode("latin1").rstrip("\0")
    (h["kernel_size"], h["kernel_addr"], h["ramdisk_size"], h["ramdisk_addr"],
     h["second_size"], h["second_addr"], h["tags_addr"], h["page_size"],
     h["header_version"], h["os_version"]) = struct.unpack_from("<10I", data, 8)
    h["name"] = data[48:64].split(b"\0")[0].decode("latin1")
    h["cmdline"] = data[64:576].split(b"\0")[0].decode("latin1")
    h["extra_cmdline"] = data[608:1632].split(b"\0")[0].decode("latin1")
    if h["header_version"] >= 1:
        h["recovery_dtbo_size"] = struct.unpack_from("<I", data, 1632)[0]
        h["recovery_dtbo_offset"] = struct.unpack_from("<Q", data, 1636)[0]
        h["header_size"] = struct.unpack_from("<I", data, 1644)[0]
    if h["header_version"] >= 2:
        h["dtb_size"] = struct.unpack_from("<I", data, 1648)[0]
        h["dtb_addr"] = struct.unpack_from("<Q", data, 1652)[0]
    return h


def fdt_nodes(blob):
    """Yield (path, props) for a flattened device tree."""
    (magic, total, off_struct, off_strings, off_rsv, version, last_comp,
     boot_cpu, size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    if magic != 0xD00DFEED:
        raise ValueError("not an FDT")
    strings = blob[off_strings:off_strings + size_strings]
    pos = off_struct
    path = []
    while pos < off_struct + size_struct:
        tok = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if tok == TOK_BEGIN:
            end = blob.index(b"\0", pos)
            name = blob[pos:end].decode("latin1")
            pos = align_raw(end + 1)
            path.append(name)
        elif tok == TOK_END_NODE:
            if path:
                path.pop()
        elif tok == TOK_PROP:
            length, nameoff = struct.unpack_from(">II", blob, pos)
            pos += 8
            value = blob[pos:pos + length]
            pos = align_raw(pos + length)
            end = strings.index(b"\0", nameoff)
            pname = strings[nameoff:end].decode("latin1")
            yield "/" + "/".join(p for p in path if p) or "/", pname, value
        elif tok == TOK_NOP:
            pass
        elif tok == TOK_END:
            break
        else:
            raise ValueError(f"bad token {tok:#x} at {pos:#x}")


def align_raw(v):
    return (v + 3) & ~3


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    h = parse_header(data)
    if h["magic"] != "ANDROID!":
        raise SystemExit(f"not a boot image: magic={h['magic']!r}")
    page = h["page_size"]
    kernel_off = page
    ramdisk_off = align(kernel_off + h["kernel_size"], page)
    second_off = align(ramdisk_off + h["ramdisk_size"], page)
    end_second = second_off + h["second_size"]
    dtbo_off = align(end_second, page)
    dtb_off = align(dtbo_off + h.get("recovery_dtbo_size", 0), page)

    (out / "kernel").write_bytes(data[kernel_off:kernel_off + h["kernel_size"]])
    if h["ramdisk_size"]:
        (out / "ramdisk").write_bytes(
            data[ramdisk_off:ramdisk_off + h["ramdisk_size"]])
    if h.get("dtb_size"):
        (out / "dtb-table.bin").write_bytes(
            data[dtb_off:dtb_off + h["dtb_size"]])

    # Every FDT in the image, in file order (Qualcomm appends a DTB table to
    # the kernel, and v2 headers may carry one explicitly).
    fdt_offsets = []
    start = 0
    while True:
        i = data.find(FDT_MAGIC, start)
        if i < 0:
            break
        total = struct.unpack_from(">I", data, i + 4)[0]
        if 0x100 <= total <= 0x400000 and i + total <= len(data):
            fdt_offsets.append((i, total))
            start = i + total
        else:
            start = i + 4

    summary = dict(header=h, page=page, dtb_off=dtb_off,
                   kernel_hdr=f"{data[kernel_off:kernel_off + 2].hex()}",
                   fdt_offsets=[dict(offset=o, size=s) for o, s in fdt_offsets])
    (out / "boot.json").write_text(json.dumps(summary, indent=2))

    print(f"magic={h['magic']} version={h['header_version']} page={page} "
          f"name={h['name']!r}")
    print(f"kernel: size={h['kernel_size']} addr={h['kernel_addr']:#x} "
          f"off={kernel_off:#x} first2={summary['kernel_hdr']}")
    print(f"ramdisk: size={h['ramdisk_size']} addr={h['ramdisk_addr']:#x} "
          f"off={ramdisk_off:#x}")
    print(f"second: size={h['second_size']} addr={h['second_addr']:#x}")
    print(f"tags_addr={h['tags_addr']:#x} dtb_size={h.get('dtb_size', 0)} "
          f"dtb_addr={h.get('dtb_addr', 0):#x}")
    print(f"cmdline={h['cmdline']!r}")
    print(f"extra_cmdline={h['extra_cmdline']!r}")
    print(f"FDTs: {len(fdt_offsets)}")
    for o, s in fdt_offsets:
        print(f"  offset={o:#x} size={s}")


if __name__ == "__main__":
    main()
