#!/usr/bin/env python3
"""Create Aloha's `nubia-nx627j` device directory from `xiaomi-raphael`.

Aloha's SurfaceDuo1NoSb.dsc is fully parameterised on TARGET_DEVICE: it
includes Device/$(TARGET_DEVICE)/{Defines,DXE,PcdsFixedAtBuild}.dsc.inc and
pulls PlatformMemoryMapLib / PlatformConfigurationMapLib from the same
directory. So a new device is just a directory with those files; nothing in
the DSC has to change.

What this script adapts, and what it deliberately leaves alone:

  * DeviceTreeBlob/Android/android-nx627j.dtb  <- the Z20 DTB (required)
  * PcdsFixedAtBuild.dsc.inc                    <- 1080x2340, Nubia Z20 strings
  * text references to raphael                  <- renamed to nx627j
  * Library/PlatformMemoryMapLib                <- KEPT: the SM8150 map already
    covers 4/6/8/10/12 GB (see the memory-hole comments); nothing is Z20-only.
  * Binaries/ and PatchedBinaries/              <- COPIED from raphael. These are
    vendor DXE drivers extracted from a phone's xbl; raphael's may work well
    enough to boot, but replacing them with drivers extracted from the Z20's own
    xbl (WOA-Project/UEFIReader) is the correct final step.

Usage:
  python scripts/aloha_nx627j_device.py --aloha-root path/to/uefi \\
      --dtb inputs/uefi-prebuilt/nx627j.dtb [--force]
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

TEMPLATE = "xiaomi-raphael"
TARGET = "nubia-nx627j"


def _rewrite_text(path, old, new):
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8",
                    errors="surrogateescape")
    return True


def _set_pcd(path, key, value):
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    pattern = re.compile(rf"^({re.escape(key)}\|).*$", re.MULTILINE)
    if not pattern.search(text):
        return False
    path.write_text(pattern.sub(rf"\g<1>{value}", text), encoding="utf-8",
                    errors="surrogateescape")
    return True


def ensure_device(aloha_root, dtb, force=False, log=print):
    """Create (or refresh) Device/nubia-nx627j under an Aloha checkout."""
    aloha_root = Path(aloha_root)
    device_root = aloha_root / "Platforms" / "SurfaceDuo1Pkg" / "Device"
    src = device_root / TEMPLATE
    dst = device_root / TARGET
    dtb = Path(dtb)

    if not src.is_dir():
        raise SystemExit(f"aloha: template device dir not found: {src}")
    if not dtb.is_file() or dtb.stat().st_size <= 1024:
        raise SystemExit(f"aloha: DTB missing or placeholder: {dtb}")

    if dst.exists():
        if not force:
            log(f"aloha: {dst.name} already exists (use --force to rebuild)")
            return dst
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    log(f"aloha: copied {src.name} -> {dst.name}")

    # 1. the device tree
    android = dst / "DeviceTreeBlob" / "Android"
    linux = dst / "DeviceTreeBlob" / "Linux"
    for blob in list(android.glob("*.dtb")) + list(linux.glob("*.dtb")):
        blob.unlink()
    (android / "android-nx627j.dtb").write_bytes(dtb.read_bytes())
    # Aloha's FDF references both variants; the Linux one is a "dummy" placeholder
    # in every device dir (see xiaomi-raphael), so keep that convention.
    linux.mkdir(parents=True, exist_ok=True)
    (linux / "linux-nx627j.dtb").write_text("dummy\n")
    log(f"aloha: DTB {dtb.name} ({dtb.stat().st_size} bytes) -> "
        f"android-nx627j.dtb (+ linux placeholder)")

    # 2. the PCDs that carry the panel and the SMBIOS identity
    pcd = dst / "PcdsFixedAtBuild.dsc.inc"
    if pcd.is_file():
        for key, value in (
            ("gAndromedaPkgTokenSpaceGuid.PcdMipiFrameBufferWidth", "1080"),
            ("gAndromedaPkgTokenSpaceGuid.PcdMipiFrameBufferHeight", "2340"),
            ("gEfiMdeModulePkgTokenSpaceGuid.PcdVideoHorizontalResolution", "1080"),
            ("gEfiMdeModulePkgTokenSpaceGuid.PcdVideoVerticalResolution", "2340"),
            ("gEfiMdeModulePkgTokenSpaceGuid.PcdSetupVideoHorizontalResolution", "1080"),
            ("gEfiMdeModulePkgTokenSpaceGuid.PcdSetupVideoVerticalResolution", "2340"),
            ("gAndromedaPkgTokenSpaceGuid.PcdSmbiosSystemBrand", '"Nubia"'),
            ("gAndromedaPkgTokenSpaceGuid.PcdSmbiosSystemModel", '"Z20"'),
            ("gAndromedaPkgTokenSpaceGuid.PcdSmbiosSystemRetailModel", '"nx627j"'),
            ("gAndromedaPkgTokenSpaceGuid.PcdSmbiosSystemRetailSku", '"MP"'),
            ("gAndromedaPkgTokenSpaceGuid.PcdABLProduct", '"Nubia Z20"'),
        ):
            if not _set_pcd(pcd, key, value):
                log(f"aloha: note: {key} not present in {pcd.name}")
        log("aloha: PCDs updated (1080x2340, Nubia Z20)")

    # 2b. the loader modules. The raphael DXE lists do not carry them, so a
    # device copied from raphael boots to the UEFI frontpage instead of the
    # UniXNU menu. Guacamole's lists are the reference for which modules the
    # boot chain needs (application, app driver, DarwinBoot, payload volume).
    for name, lines in (
        ("DXE.dsc.inc", (
            "AndromedaPkg/Driver/ShengBootMemoryDxe/ShengBootMemoryDxe.inf",
            "UniXNUPkg/Application/UniXNU/UniXNU.inf",
            "UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf",
            "DarwinBootPkg/Driver/DarwinBoot.inf",
        )),
        ("DXE.inc", (
            "INF UniXNUPkg/Application/UniXNU/UniXNU.inf",
            "INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf",
            "INF DarwinBootPkg/Driver/DarwinBoot.inf",
            "INF AndromedaPkg/Driver/ShengBootMemoryDxe/ShengBootMemoryDxe.inf",
        )),
    ):
        path = dst / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="surrogateescape")
            if "ShengBootMemoryDxe" not in text:
                path.write_text(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n",
                                encoding="utf-8", errors="surrogateescape")
                log(f"aloha: {name}: added the loader modules")

    # 3. any remaining textual reference to the template
    for path in dst.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".inc", ".inf", ".c", ".h", ".dsc"):
            _rewrite_text(path, "xiaomi-raphael", TARGET)
            _rewrite_text(path, "android-raphael.dtb", "android-nx627j.dtb")
            _rewrite_text(path, "raphael", "nx627j")
    log("aloha: text references renamed")

    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aloha-root", required=True, help="Aloha checkout (the dir with Platforms/)")
    ap.add_argument("--dtb", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    ensure_device(args.aloha_root, args.dtb, force=args.force)
    print("done")


if __name__ == "__main__":
    main()
