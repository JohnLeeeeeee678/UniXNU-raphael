#!/usr/bin/env python3
"""Build the Aloha NOSB firmware volume with the UniXNU/DarwinBoot INFs.

The Aloha tree ships a first-class ``xiaomi-raphael`` device directory
(Device/xiaomi-raphael with its own DeviceTreeBlob), so unlike guacamole we do
NOT have to clone another vendor's device dir. The DSC selects it purely via
``TARGET_DEVICE`` and PlatformBuildNoSb derives ``FDT`` from it, both of which
board.toml sets.

For nx627j (Nubia Z20) stage 1 we reuse that directory unchanged except for the
device tree blob: ``inputs/uefi-prebuilt/nx627j.dtb`` (supplied by
scripts/get-nx627j-dtb.sh) replaces ``android-<FDT stem>.dtb`` in place, so the
FDT *name* stays raphael.dtb while the *content* is the Z20's. Once a native
``nubia-nx627j`` device dir exists in Aloha (stage 2), only TARGET_DEVICE in
board.toml has to change and this override becomes a no-op.

The aloha-guacamole.patch creates ``Resources/Configs/guacamole.toml``; we
mirror it to the config name board.toml sets because the UniXNU firmware driver
reads ``Resources/Configs/<config>.toml``.
"""
import os
import shutil
import sys
import tomllib
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unixnu" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

from unixnu import firmware  # noqa: E402
from tree import assemble  # noqa: E402

UEFI = ROOT / "uefi"
EDK2 = UEFI / "MU_BASECORE"

board = tomllib.loads((ROOT / "board.toml").read_text())
DEFINES = board.get("firmware", {}).get("defines", {})
TARGET_DEVICE = DEFINES.get("TARGET_DEVICE", "xiaomi-raphael")
FDT = DEFINES.get("FDT", "raphael.dtb")
CONFIG_NAME = board.get("firmware", {}).get("config", "raphael")
KIT = board.get("board", {}).get("kit", "raphael")

WORK = ROOT / "out" / "raphael"
TREE = assemble(WORK, ROOT / "unixnu", ROOT)
LOGS = WORK / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

DEVICE_ROOT = UEFI / "Platforms" / "SurfaceDuo1Pkg" / "Device"
DST = DEVICE_ROOT / TARGET_DEVICE
SRC = DEVICE_ROOT / "oneplus-guacamole"
dtb_override = ROOT / "inputs" / "uefi-prebuilt" / f"{KIT}.dtb"

# Stage 2: Aloha has no nubia-nx627j directory, so build one from the raphael
# template (same SM8150, same 1080x2340 panel). See scripts/aloha_nx627j_device.py.
if TARGET_DEVICE == "nubia-nx627j" and not DST.is_dir():
    from aloha_nx627j_device import ensure_device
    ensure_device(UEFI, dtb_override, log=print)

# The named device dir is shipped by the Aloha tree; only synthesise it as a
# fallback (same SM8150 silicon) if a future revision drops it.
if not DST.is_dir():
    if not SRC.is_dir():
        raise SystemExit(
            f"firmware: neither {DST} nor {SRC} exists in the Aloha tree; "
            f"cannot build the {TARGET_DEVICE} device."
        )
    print(f"firmware: {DST.name} missing; cloning {SRC.name} (same SM8150 silicon)")
    shutil.copytree(SRC, DST)
    for old, new in (
        ("android-guacamole.dtb", f"android-{Path(FDT).stem}.dtb"),
        ("linux-guacamole.dtb", f"linux-{Path(FDT).stem}.dtb"),
        ("guacamole.toml", f"{CONFIG_NAME}.toml"),
    ):
        p = DST / old
        if p.is_file():
            p.rename(DST / new)
else:
    print(f"firmware: using Aloha device dir {DST.name}")

# The UniXNU firmware driver reads Resources/Configs/<config>.toml; the SM8150
# patch only provides the guacamole one.
cfg_src = UEFI / "Resources" / "Configs" / "guacamole.toml"
cfg_dst = UEFI / "Resources" / "Configs" / f"{CONFIG_NAME}.toml"
if cfg_src.is_file() and not cfg_dst.is_file():
    shutil.copy(cfg_src, cfg_dst)
    print(f"firmware: created {cfg_dst.name}")

# Stage 1 only: when TARGET_DEVICE is still raphael, swap the DTB content
# while keeping the raphael file name. With the generated nubia-nx627j dir
# (stage 2) the blob is already in place and this is a no-op copy.
android_dtb = DST / "DeviceTreeBlob" / "Android" / f"android-{Path(FDT).stem}.dtb"
if dtb_override.is_file() and dtb_override.stat().st_size > 1024:
    if not android_dtb.is_file():
        raise SystemExit(
            f"firmware: DTB override given ({dtb_override}) but the Aloha tree "
            f"has no {android_dtb}; check TARGET_DEVICE/FDT in board.toml."
        )
    shutil.copyfile(dtb_override, android_dtb)
    print(f"firmware: replaced {android_dtb.name} with {dtb_override.name} "
          f"({dtb_override.stat().st_size} bytes)")
else:
    print(f"firmware: no {dtb_override.name}; keeping the Aloha DTB as-is")

ctx = types.SimpleNamespace(
    board=board,
    tree=TREE,
    work=WORK,
    logs=LOGS,
    jobs=8,
    args=types.SimpleNamespace(skip_preflight=False),
    uefi=UEFI,
)
# DEBUG builds enable EDK II ASSERTs; a driver that trips one dead-loops
# (black screen until the bootloader watchdog resets the phone).
TARGET = os.environ.get("FW_TARGET", "DEBUG")
firmware.build(ctx, None, UEFI, EDK2, TARGET)
