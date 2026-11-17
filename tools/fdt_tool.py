#!/usr/bin/env python3
"""List / extract the device trees inside an unpacked boot image.

Usage:
  python tools/fdt_tool.py list  boot.img
  python tools/fdt_tool.py split boot.img outdir     # writes fdt-00.dtb ...
  python tools/fdt_tool.py dump  outdir/fdt-03.dtb   # key nodes as text
"""
import struct
import sys
from pathlib import Path

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
TOK_BEGIN, TOK_END_NODE, TOK_PROP, TOK_NOP, TOK_END = 1, 2, 3, 4, 9
WANT = {
    "model", "compatible", "reg", "qcom,board-id", "qcom,msm-id",
    "qcom,mdss-dsi-panel-width", "qcom,mdss-dsi-panel-height",
    "qcom,mdss-dsi-panel-framerate", "qcom,mdss-dsi-panel-name",
    "qcom,mdss-dsi-panel-type", "clock-frequency", "qcom,level",
}


def align4(v):
    return (v + 3) & ~3


def cstr(value):
    return value.split(b"\0")[0].decode("latin1")


def parse(blob):
    (magic, total, off_struct, off_strings, off_rsv, version, last_comp,
     boot_cpu, size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    if magic != 0xD00DFEED:
        raise ValueError("not an FDT")
    strings = blob[off_strings:off_strings + size_strings]
    pos = off_struct
    path = []
    out = []
    while pos < off_struct + size_struct:
        tok = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if tok == TOK_BEGIN:
            end = blob.index(b"\0", pos)
            path.append(blob[pos:end].decode("latin1"))
            pos = align4(end + 1)
        elif tok == TOK_END_NODE:
            if path:
                path.pop()
        elif tok == TOK_PROP:
            length, nameoff = struct.unpack_from(">II", blob, pos)
            pos += 8
            value = blob[pos:pos + length]
            pos = align4(pos + length)
            end = strings.index(b"\0", nameoff)
            out.append(("/" + "/".join(p for p in path if p) or "/",
                        strings[nameoff:end].decode("latin1"), value))
        elif tok == TOK_NOP:
            pass
        elif tok == TOK_END:
            break
    return out


def fdt_offsets(data):
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


def cmd_list(img):
    data = Path(img).read_bytes()
    for idx, (off, size) in enumerate(fdt_offsets(data)):
        blob = data[off:off + size]
        props = {}
        for path, name, value in parse(blob):
            if path == "/" and name in ("model", "compatible", "qcom,board-id"):
                props[name] = value
        model = cstr(props.get("model", b""))
        compat = " ".join(cstr(v) for v in props.get("compatible", b"").split(b"\0") if v)
        board = props.get("qcom,board-id", b"")
        print(f"[{idx:02d}] off={off:#x} size={size} model={model!r} "
              f"compat={compat!r} board-id={board.hex()}")


def cmd_split(img, outdir):
    data = Path(img).read_bytes()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for idx, (off, size) in enumerate(fdt_offsets(data)):
        (out / f"fdt-{idx:02d}.dtb").write_bytes(data[off:off + size])
    print(f"wrote {len(fdt_offsets(data))} FDTs to {out}")


def cmd_dump(dtb):
    blob = Path(dtb).read_bytes()
    for path, name, value in parse(blob):
        if name not in WANT:
            continue
        if name == "reg":
            cells = struct.unpack(f">{len(value) // 4}I", value)
            shown = " ".join(f"{c:#x}" for c in cells)
        elif name in ("compatible", "model", "qcom,mdss-dsi-panel-name",
                      "qcom,mdss-dsi-panel-type"):
            shown = " | ".join(cstr(v) for v in value.split(b"\0") if v)
        else:
            shown = value.hex()
        print(f"{path:60s} {name:38s} {shown}")


def main():
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list(sys.argv[2])
    elif cmd == "split":
        cmd_split(sys.argv[2], sys.argv[3])
    elif cmd == "dump":
        cmd_dump(sys.argv[2])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
