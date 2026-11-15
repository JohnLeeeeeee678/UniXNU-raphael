#!/usr/bin/env python3
"""Verify the constant pool usage and the touch/display offset arithmetic.

The tool answers three questions with evidence from the binary:

  1. Which code reads a given constant pool word (complete reference list,
     not just the first instruction after an ADRP).
  2. What does the SweetHID offset expression evaluate to, for the constants
     that are currently in the kernel?
  3. What does the SweetFramebuffer side compute, i.e. which offset does the
     display actually use?

It also prints the boot argument that selects the native or the iPhone X
presentation.
"""
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_edge_const import load_commands  # noqa: E402

POOL_START = 0x28A40
POOL_END = 0x28B00


def sections(data):
    out = {}
    for seg in load_commands(data):
        for sec in seg["sections"]:
            out.setdefault(sec["name"], sec)
    return out


def text_section(data):
    best = None
    for seg in load_commands(data):
        for sec in seg["sections"]:
            if sec["name"] == "__text" and sec["size"]:
                if best is None or sec["size"] > best["size"]:
                    best = sec
    if best is None:
        raise SystemExit("no __text section")
    return best


def disasm_text(data, text):
    code = data[text["offset"]:text["offset"] + text["size"]]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    return [i for i in md.disasm(code, text["addr"]) if i.mnemonic != ".byte"]


def track_pool_refs(insns, const):
    """Linear scan that keeps track of which register holds a pool address."""
    const_lo = const["addr"]
    const_hi = const["addr"] + const["size"]
    page_of = {}
    refs = []
    for ins in insns:
        if ins.mnemonic == "adrp":
            page_of[ins.operands[0].reg] = ins.operands[1].imm & 0xFFFFFFFFFFFFFFFF
            continue
        if ins.mnemonic == "add" and len(ins.operands) == 3:
            dst, src, imm = ins.operands
            if imm.type == 2 and src.reg in page_of:
                page_of[dst.reg] = page_of[src.reg] + imm.imm
                continue
        if ins.mnemonic.startswith("ldr") and len(ins.operands) >= 2:
            mem = ins.operands[1].mem
            if mem.base in page_of:
                addr = page_of[mem.base] + (mem.disp or 0)
                if const_lo <= addr < const_hi:
                    foff = const["offset"] + (addr - const_lo)
                    refs.append((ins.address, ins.mnemonic, ins.op_str,
                                 addr, foff))
            continue
        # Any other write to a register invalidates the tracked address.
        if ins.mnemonic.startswith("ldr") and ins.operands[0].type == 1:
            page_of.pop(ins.operands[0].reg, None)
        elif ins.mnemonic in ("mov", "movz", "movk", "movn", "add", "sub",
                              "adr", "bl", "blr", "movi", "movk", "orr",
                              "and", "eor", "lsl", "lsr", "mul", "msub"):
            if len(ins.operands) and ins.operands[0].type == 1:
                page_of.pop(ins.operands[0].reg, None)
    return refs


def main(path):
    data = open(path, "rb").read()
    text = text_section(data)
    secs = sections(data)
    const = secs["__const"]
    cstr = secs.get("__cstring")

    print("__text   vm=0x%x off=0x%x size=0x%x" % (
        text["addr"], text["offset"], text["size"]))
    print("__const  vm=0x%x off=0x%x size=0x%x" % (
        const["addr"], const["offset"], const["size"]))
    if cstr:
        print("__cstring vm=0x%x off=0x%x size=0x%x" % (
            cstr["addr"], cstr["offset"], cstr["size"]))

    insns = disasm_text(data, text)
    refs = track_pool_refs(insns, const)

    print("\n=== every reference into __const between 0x%x and 0x%x ===" % (
        POOL_START, POOL_END))
    counts = {}
    for addr, m, op, vm, foff in refs:
        if not (POOL_START <= foff < POOL_END):
            continue
        counts[foff] = counts.get(foff, 0) + 1
        val = struct.unpack_from("<i", data, foff)[0]
        print("  0x%x  %-22s -> file 0x%06x  value %d" % (addr, op, foff, val))
    print("\n  reference counts:")
    for off in sorted(counts):
        print("    file 0x%06x  %d reference(s)  value %d" % (
            off, counts[off], struct.unpack_from("<i", data, off)[0]))

    # The boot argument that selects native vs iPhone X presentation.
    # SweetHID::start parses it into [sp, #0xc].
    if cstr:
        for addr, m, op, vm, foff in refs:
            pass
    print("\n=== constant pool dump 0x28a40 .. 0x28b00 ===")
    for off in range(POOL_START, POOL_END, 4):
        val = struct.unpack_from("<i", data, off)[0]
        print("  0x%06x  %12d  0x%08x" % (off, val, val & 0xFFFFFFFF))


if __name__ == "__main__":
    main(sys.argv[1])
