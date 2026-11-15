"""Locate the SWEET_TOUCH_EDGE_PX constant inside a Mach-O kernel.

The 0071 patch tests `y > 2399 - 48` with the panel height hard coded for
the 1080x2400 guacamole screen.  Redmi K20 Pro (raphael) is 1080x2340, so the
test can never succeed and the digitizer never reports an edge tip.  The
threshold is a plain immediate in the compiled code, so patching the binary
is enough -- no kernel rebuild required.
"""
import struct
import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

MACHO_MAGIC_64 = 0xFEEDFACF


def load_commands(data):
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = \
        struct.unpack_from("<IiiIIIII", data, 0)
    assert magic == MACHO_MAGIC_64, hex(magic)
    off = 32
    segments = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            segname = data[off + 8:off + 24].rstrip(b"\x00").decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, off + 24)
            maxprot, initprot, nsects, flags_seg = struct.unpack_from("<IIiI", data, off + 56)
            sections = []
            soff = off + 72
            for _ in range(nsects):
                sectname = data[soff:soff + 16].rstrip(b"\x00").decode()
                segofsect = data[soff + 16:soff + 32].rstrip(b"\x00").decode()
                addr, size = struct.unpack_from("<QQ", data, soff + 32)
                offset = struct.unpack_from("<I", data, soff + 48)[0]
                align, reloff, nreloc, sflags = struct.unpack_from("<IIiI", data, soff + 56)
                sections.append({
                    "name": sectname, "seg": segofsect, "addr": addr,
                    "size": size, "offset": offset, "flags": sflags,
                })
                soff += 80
            segments.append({
                "name": segname, "vmaddr": vmaddr, "vmsize": vmsize,
                "fileoff": fileoff, "filesize": filesize, "sections": sections,
            })
        off += cmdsize
    return segments


def section_by_name(segments, seg, sect):
    for s in segments:
        if s["name"] == seg:
            for x in s["sections"]:
                if x["name"] == sect:
                    return x
    return None


def main(path):
    data = open(path, "rb").read()
    segments = load_commands(data)
    for s in segments:
        print("SEG %-16s vm=0x%x filesz=0x%x  sections=%s" % (
            s["name"], s["vmaddr"], s["filesize"],
            [x["name"] for x in s["sections"]]))

    text = None
    for s in segments:
        for x in s["sections"]:
            if x["name"] == "__text" and x["size"]:
                if text is None or x["size"] > text["size"]:
                    text = x
    if text is None:
        print("no __text")
        return
    code = data[text["offset"]:text["offset"] + text["size"]]
    base = text["addr"]
    print("\n__text: file 0x%x..0x%x  vm 0x%x..0x%x  size %d" % (
        text["offset"], text["offset"] + text["size"], base, base + text["size"], len(code)))

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True

    targets = {2351: "2351 (2399-48)", 2399: "2399", 1079: "1079", 1031: "1031 (1079-48)",
               48: "48", 2340: "2340", 2436: "2436", 2400: "2400"}
    hits = {}

    # First pass: collect every instruction carrying an interesting immediate.
    instructions = list(md.disasm(code, base))
    print("decoded %d instructions" % len(instructions))
    for ins in instructions:
        for op in ins.operands:
            if op.type == 2:  # ARM64_OP_IMM
                if op.imm in targets:
                    hits.setdefault(op.imm, []).append((ins.address, ins.mnemonic, ins.op_str))

    for imm in sorted(hits):
        lst = hits[imm]
        print("\n== immediate %d (%s): %d hits" % (imm, targets[imm], len(lst)))
        for addr, mn, ops in lst[:12]:
            print("   0x%x  %s %s" % (addr, mn, ops))

    # Second pass: find the IOLog string reference so we can identify the
    # function that owns the edge test.
    needle = b"SWEET HID: touch %d %s at %d,%d%s"
    idx = data.find(needle)
    print("\nstring 'SWEET HID: touch' at file offset 0x%x" % idx)
    if idx < 0:
        return
    # The string lives in __TEXT,__cstring; compute its virtual address.
    cstr = section_by_name(segments, "__TEXT", "__cstring")
    str_va = None
    if cstr and cstr["offset"] <= idx < cstr["offset"] + cstr["size"]:
        str_va = cstr["addr"] + (idx - cstr["offset"])
        print("string vm address 0x%x" % str_va)
    else:
        for s in segments:
            for x in s["sections"]:
                if x["offset"] <= idx < x["offset"] + x["size"]:
                    str_va = x["addr"] + (idx - x["offset"])
                    print("string in %s,%s vm 0x%x" % (x["seg"], x["name"], str_va))
    if str_va is None:
        return

    # Find the pointer to that address anywhere in the file.
    ptr = struct.pack("<Q", str_va)
    pos = data.find(ptr)
    seen = []
    while pos >= 0 and len(seen) < 20:
        va = None
        for s in segments:
            if s["fileoff"] <= pos < s["fileoff"] + s["filesize"]:
                va = s["vmaddr"] + (pos - s["fileoff"])
        print("pointer to string at file 0x%x vm %s" % (pos, hex(va) if va else "?"))
        seen.append(pos)
        pos = data.find(ptr, pos + 1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "D:/raphael-ios/work/kernel_0111.macho")
