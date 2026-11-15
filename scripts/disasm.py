"""Strict A64 disassembler for the SWEET kernel.

capstone's linear sweep with skipdata=True can silently lose 4 byte
alignment when it has to skip a byte, which shifts every following
instruction by one byte.  That produces plausible looking but wrong
output, so this helper refuses to skip: it disassembles from a given
address and verifies that every decoded instruction is exactly 4 bytes
long and that the bytes are covered exactly once.
"""
import struct
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, ".")
from find_edge_const import load_commands  # noqa: E402


def text_section(data):
    text = None
    for seg in load_commands(data):
        for sec in seg["sections"]:
            if sec["name"] == "__text" and sec["size"]:
                if text is None or sec["size"] > text["size"]:
                    text = sec
    if text is None:
        raise SystemExit("no __text section")
    return text


def va_to_off(text, va):
    off = text["offset"] + (va - text["addr"])
    if off < text["offset"] or off >= text["offset"] + text["size"]:
        raise SystemExit("va 0x%x outside __text" % va)
    return off


def disasm(data, text, va, count, label=""):
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = False
    off = va_to_off(text, va)
    cursor = off
    out = []
    for _ in range(count):
        chunk = data[cursor:cursor + 4]
        if len(chunk) < 4:
            break
        addr = text["addr"] + (cursor - text["offset"])
        ins = list(md.disasm(chunk, addr))
        if not ins:
            out.append((addr, cursor, None, chunk))
            break
        i = ins[0]
        if i.size != 4:
            raise SystemExit(
                "instruction at 0x%x is %d bytes -- stream is misaligned"
                % (i.address, i.size))
        out.append((i.address, cursor, i, chunk))
        cursor += 4
    if label:
        print("=== %s ===" % label)
    for addr, foff, i, chunk in out:
        if i is None:
            print("0x%x (f0x%x) <undecodable %s>" % (addr, foff, chunk.hex()))
        else:
            print("0x%x (f0x%x)  %-8s %-40s ; %s"
                  % (addr, foff, i.mnemonic, i.op_str, chunk.hex()))
    return out


def main():
    path = sys.argv[1]
    va = int(sys.argv[2], 16)
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    data = open(path, "rb").read()
    text = text_section(data)
    disasm(data, text, va, count)


if __name__ == "__main__":
    main()
