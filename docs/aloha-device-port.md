# The `nubia-nx627j` device directory

## Why there is nothing to patch in Aloha's DSC

`SurfaceDuo1NoSb.dsc` is parameterised end to end:

```
!include SurfaceDuo1Pkg/Device/$(TARGET_DEVICE)/Defines.dsc.inc
!include SurfaceDuo1Pkg/Device/$(TARGET_DEVICE)/DXE.dsc.inc
!include SurfaceDuo1Pkg/Device/$(TARGET_DEVICE)/PcdsFixedAtBuild.dsc.inc
PlatformMemoryMapLib|.../Device/$(TARGET_DEVICE)/Library/PlatformMemoryMapLib/...
PlatformConfigurationMapLib|.../Device/$(TARGET_DEVICE)/Library/PlatformConfigurationMapLib/...
```

So adding a phone is exactly "add a directory with those files". No `.dsc`,
`.dec` or driver-list edit is needed, and that is why the generator can be a
plain copy-and-adapt instead of a patch series.

## What the generator does

`scripts/aloha_nx627j_device.py` (run automatically by `build-firmware.py`):

1. copies `Device/xiaomi-raphael` → `Device/nubia-nx627j` (same SM8150, same
   1080x2340 panel);
2. writes `DeviceTreeBlob/Android/android-nx627j.dtb` from
   `inputs/uefi-prebuilt/nx627j.dtb` and removes the template blobs;
3. rewrites the PCDs: 1080x2340, brand `Nubia`, model `Z20`, retail `nx627j`,
   ABL product `Nubia Z20`;
4. renames any remaining textual `raphael` references.

Run it by hand:

```sh
python3 scripts/aloha_nx627j_device.py \
    --aloha-root uefi \
    --dtb inputs/uefi-prebuilt/nx627j.dtb [--force]
```

## What is reused, and what must be replaced

| Piece | Reused from raphael? | Why |
|---|---|---|
| `Library/PlatformMemoryMapLib` | yes | generic SM8150 map; its comments cover 4/6/8/10/12 GB, `0x180000000 @ RamSize-4GB` for the upper bank |
| `Library/PlatformConfigurationMapLib` | yes | SM8150 SoC constants (TzApps, shared IMEM, 8 cores) |
| `DXE.dsc.inc`, `DXE.inc`, `APRIORI.inc` | yes | they only reference `$(TARGET_DEVICE)` paths |
| `Binaries/`, `PatchedBinaries/` | **no — temporary** | vendor DXE binaries from a phone's `xbl`; raphael's may boot, but the Z20 needs its own |

## Getting the Z20 binaries (final step)

Aloha cannot ship these; they are the vendor's. Extract them from your own
phone:

```sh
adb shell su -c 'dd if=/dev/block/bootdevice/by-name/xbl of=/sdcard/xbl.img'
adb pull /sdcard/xbl.img
# then, with WOA-Project/UEFIReader:
#   UEFIReader xbl.img out/
#   copy the driver payloads into Device/nubia-nx627j/Binaries/
```

Keep them out of git. With `Binaries/` from raphael the firmware may still
reach the menu; with the Z20's own drivers the UFS/display/USB path is the one
the hardware actually expects.

**Caveat for nx627j (measured 2026-11-17):** this route does not work on the
Z20. Its `xbl` is a monolithic firmware build — the UEFI volume inside it has a
valid `_FVH` header but no FFS files, and the image contains no `MZ`/`PE32`
payloads at all (`docs/nx627j-live-dump.md` has the evidence). So there are no
per-driver binaries to lift, and raphael's `Binaries/` stay in place unless a
complete Nubia firmware package with an unpacked UEFI FD is found.
