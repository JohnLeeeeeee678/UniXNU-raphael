#!/usr/bin/env python3
"""UniXNU ADT step for nx627j (Nubia Z20, SM8150-AC / Snapdragon 855+).

nx627j is the same SM8150 family as raphael (K20 Pro), guacamole (OnePlus 7
Pro) and nabu (Xiaomi Pad 5). The UniXNU payload driver passes the generic ADT
flags (chip-id, owned-memory-size, root-match UUID, CPU registers, PSCI method,
trust cache, ...). The nx627j hardware profile in devices.py owns those values;
this wrapper only selects it and forwards the requested DRAM sizes.

Differences from raphael that this profile carries:
  * panel 1080x2340 (EW811 AMOLED, 19.5:9) -- raphael is 1080x2340 too, but the
    profile keeps Z20's own CPU clocks (prime 2.96 GHz) and board compatible.
  * touch is a Goodix "6270" on SE17 / IRQ 122, not the GT9889 of raphael; the
    XNU touch driver still has to be taught that IC (see the live FDT dump,
    docs/nx627j-live-dump.md).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

DEVICE = "nx627j"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dram-size", default="0xc0000000")
    parser.add_argument("--owned-memory-size", type=lambda value: int(value, 0))
    parser.add_argument("--base-d22ap", default=None,
                        help="path to base-d22ap.adt (iPhone X artifact)")
    known, _unknown = parser.parse_known_args()
    tool = Path(__file__).resolve().parent / "mkadt.py"
    command = [sys.executable, str(tool), known.output, "--device", DEVICE,
               "--dram-size", known.dram_size]
    if known.owned_memory_size is not None:
        command += ["--owned-memory-size", str(known.owned_memory_size)]
    if known.base_d22ap is not None:
        env = dict(os.environ)
        env["UNIXNU_D22AP_ADT"] = known.base_d22ap
        subprocess.run(command, check=True, env=env)
        return
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
