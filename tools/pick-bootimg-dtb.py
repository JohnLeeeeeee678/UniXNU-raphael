#!/usr/bin/env python3
"""Pick the best device tree for nx627j out of a stock boot.img.

The Z20 boot image carries a Qualcomm DTB *table* (15 entries in the image we
have): reference boards plus the SM8150 v1/v2 and SM8150P v1/v2 SoC trees. The
board-level tree (with /memory, the nubia panel nodes and qcom,board-id) lives
in the `dtbo` partition on this device, so it is not in the table at all.

Selection order:
  1. an FDT whose root compatible/model names nubia / nx627j / Z20;
  2. the SM8150 v2 SoC tree (msm-id 0x153/2) -- what an 855+ boots;
  3. the SM8150 v1 tree;
  4. the first FDT in the table.

Usage: python tools/pick-bootimg-dtb.py boot.img out.dtb
"""
import struct
import sys
from pathlib import Path

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
TOK_BEGIN, TOK_END_NODE, TOK_PROP, TOK_NOP, TOK_END = 1, 2, 3, 4, 9


def align4(v):
    return (v + 3) & ~3


def cstr(v):
    return v.split(b"\0")[0].decode("latin1")


def root_props(blob):
    (magic, total, off_struct, off_strings, off_rsv, version, last_comp,
     boot_cpu, size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    strings = blob[off_strings:off_strings + size_strings]
    pos = off_struct
    depth = 0
    props = {}
    while pos < off_struct + size_struct:
        tok = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if tok == TOK_BEGIN:
            end = blob.index(b"\0", pos)
            pos = align4(end + 1)
            depth += 1
        elif tok == TOK_END_NODE:
            depth -= 1
            if depth < 0:
                break
        elif tok == TOK_PROP:
            length, nameoff = struct.unpack_from(">II", blob, pos)
            pos += 8
            value = blob[pos:pos + length]
            pos = align4(pos + length)
            if depth == 1:
                end = strings.index(b"\0", nameoff)
                props[strings[nameoff:end].decode("latin1")] = value
        elif tok == TOK_END:
            break
    return props


def fdt_entries(data):
    res, start = [], 0
    while True:
        i = data.find(FDT_MAGIC, start)
        if i < 0:
            return res
        total = struct.unpack_from(">I", data, i + 4)[0]
        if 0x100 <= total <= 0x400000 and i + total <= len(data):
            res.append((i, total))
            start = i + total
        else:
            start = i + 4


def score(props):
    compat = b" ".join(props.get("compatible", b"").split(b"\0"))
    model = props.get("model", b"").lower()
    text = (compat + b" " + model).lower()
    if b"nubia" in text or b"nx627" in text or b"z20" in text:
        return 100
    msm = props.get("qcom,msm-id", b"")
    if len(msm) >= 8:
        soc, rev = struct.unpack_from(">II", msm, 0)
        # Qualcomm encodes the revision in 0x10000 steps: 0x10000 = v1,
        # 0x20000 = v2, so an SM8150 v2 tree is <0x153 0x20000>.
        if soc == 0x153 and rev >= 0x20000:
            return 80
        if soc == 0x153:
            return 60
    return 10


def main():
    data = Path(sys.argv[1]).read_bytes()
    out = Path(sys.argv[2])
    best, best_score = None, -1
    for off, size in fdt_entries(data):
        blob = data[off:off + size]
        try:
            props = root_props(blob)
        except Exception:
            continue
        s = score(props)
        if s > best_score:
            best, best_score = (off, blob, props), s
    if best is None:
        raise SystemExit("no FDT found in the boot image")
    off, blob, props = best
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    print(f"picked FDT at {off:#x} ({len(blob)} bytes) score={best_score} "
          f"model={cstr(props.get('model', b''))!r} "
          f"compat={cstr(props.get('compatible', b''))!r}")
    if best_score < 80:
        print("WARNING: no SM8150 or nubia tree matched; this is a guess.")


if __name__ == "__main__":
    main()
