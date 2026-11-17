# nx627j (Nubia Z20) — UniXNU port, stage 1

This fork of [UniXNU-raphael](https://github.com/JohnLeeeeeee678/UniXNU-raphael)
adds a **Nubia Z20 (nx627j, SM8150-AC / Snapdragon 855+)** device profile to the
SM8150 UniXNU bring-up.

Same silicon as raphael (K20 Pro), guacamole (OnePlus 7 Pro) and nabu
(Xiaomi Pad 5), so the XNU kernel, the Aloha UEFI SM8150 platform and the
DarwinBoot payload are reused unchanged. Only two things are device-specific:

1. the panel/touch/clock profile in `scripts/devices.py` (`nx627j` entry),
2. the device tree blob the UEFI and the shim read.

## What was changed

| File | Change |
|---|---|
| `scripts/devices.py` | new `nx627j` profile: 1080x2340 panel, Kryo 485 with 2.96 GHz prime, GIC/UFS/timer from the Z20's own boot.img DTB table |
| `board.toml` | board `nx627j`; ADT step → `make-nx627j-adt.py`; keeps raphael's Aloha device dir (stage 1) |
| `scripts/make-nx627j-adt.py` | `mkadt.py --device nx627j` wrapper (same interface as the raphael one) |
| `scripts/get-nx627j-dtb.sh` | takes `inputs/nx627j.dtb`, falls back to raphael's DTB with a warning |
| `scripts/build-firmware.py` | DTB override: copies `inputs/uefi-prebuilt/nx627j.dtb` over the Aloha device dir's `android-raphael.dtb` |
| `scripts/build-bootimg.py` | artifact names derive from the board `kit` (`boot-nx627j.img`) |
| `.github/workflows/build-nx627j.yml` | the raphael workflow, retargeted |

## What the Z20 boot.img actually contains

Parsed with `tools/unpack_boot.py` and `tools/fdt_tool.py` (header **v2**,
page 4096, kernel at `0x8000`, tags at `0x100`, DTB table at `0x23f2000`,
15 device trees):

* the table holds Qualcomm reference boards plus **SM8150 v1/v2 and SM8150P
  v1/v2 SoC trees** — and **no nubia board tree**. On this device the board DT
  (the one with `/memory`, the panel nodes and `qcom,board-id`) is applied from
  the **`dtbo` partition**, so it is not in `boot.img` at all;
* the SM8150 v2 tree in that table still confirms the values this port needs:
  GIC `0x17a00000` + `0x17a60000`, timer 19.2 MHz, UFS `0x1d84000`, and
  `reserved-memory/cont_splash_region` = `0x9c000000` + `0x2400000` (36 MiB);
* its `/memory` is `0x0 0x0` — the bootloader patches the real banks in, so the
  memory values in `devices.py` remain the SM8150 reference ones.

`tools/pick-bootimg-dtb.py boot.img out.dtb` picks the SM8150 v2 tree;
`scripts/get-nx627j-dtb.sh` does that automatically when `boot.img` sits at the
repo root. For the real board DTB, either dump `/sys/firmware/fdt` on the phone
or pull the `dtbo` partition and feed it in as `inputs/nx627j.dtb`.
The full field-by-field dump is in `docs/bootimg-analysis.md`.

## Device inputs (already collected)

The Z20 has been dumped in TWRP recovery with root ADB, so the board-level
inputs exist and are no longer a blocker:

* **merged FDT** — 652,509 B from `/sys/firmware/fdt`, carrying the EW811 panel,
  the Goodix 6270 touch node, `nubia_hw_gpio_ctrl` and a populated `/memory`.
  Drop it at `inputs/nx627j.dtb` and `scripts/get-nx627j-dtb.sh` picks it up
  before it falls back to the SoC tree from `boot.img`.
* **`xbl` / `xblbak`** — 3.5 MiB ELF each; the UEFI firmware volume sits at
  `0x9fc00000` (2.25 MiB). It turned out to be **monolithic**: valid `_FVH`
  header, no FFS files, no `PE32` images, so this phone cannot give Aloha
  per-driver DXE binaries. Stage 2 keeps raphael's `Binaries/`.
* **`dtbo`** — 23 overlays, entry 0 selected by `androidboot.dtbo_idx=0`.

Sizes, hashes and every extracted fact are in
[`docs/nx627j-live-dump.md`](docs/nx627j-live-dump.md). The dumps themselves are
binary and stay out of git.

## Getting the board DTB into CI

`inputs/` is gitignored, so a fresh clone (and therefore CI) has no
`inputs/nx627j.dtb` and `scripts/get-nx627j-dtb.sh` falls back to raphael's DTB
— same resolution, wrong panel nodes. To build with the real one, run the
**build-nx627j** workflow with its `dtb_url` input set to a URL that returns the
raw FDT (magic `d00dfeed`); the script fetches it, checks the magic and records
its sha256 in the log. Locally, just drop the file at `inputs/nx627j.dtb`.

## Build

Fork this repo, enable Actions, run **build-nx627j**. It chains:

1. `kernel` (macos-15): XNU 8796 with `MACHINE_CONFIG=SWEET`, staged as
   `inputs/raphael/kernel.macho`;
2. `build` (ubuntu-latest): Aloha UEFI + payload + boot image, artifact
   `boot-nx627j.img`.

Local build works the same way as the upstream repo (Linux, EDK II deps + a
prebuilt kernel under `inputs/raphael/kernel.macho`):

```sh
bash scripts/get-nx627j-dtb.sh
python3 scripts/get-base-d22ap.sh
python3 scripts/build-firmware.py
python3 scripts/build-payload.py
python3 scripts/build-bootimg.py
```

## Boot it

```sh
fastboot boot boot-nx627j.img     # RAM only, nothing written, reboot = Android
```

Watch for, in order:

1. UniXNU menu or Aloha splash (UEFI came up);
2. `DARWINBOOT: hand-off to the kernel`;
3. XNU console. The kernel is built with `sweetusb=2`, so the log comes out of
   the USB port as CDC-ACM (`/dev/ttyACM*` on Linux, COMx on Windows);
4. launchd, then SpringBoard.

The iOS root has to be flashed once into `userdata` as an HFS+ volume — see
`FLASH-ROOT.md` upstream. **That step erases the phone's user data.**

## Stage 1 vs stage 2

* **Stage 2 (default, this commit)** — `scripts/build-firmware.py` calls
  `scripts/aloha_nx627j_device.py`, which copies Aloha's `xiaomi-raphael` device
  dir to `nubia-nx627j`, drops in the Z20 DTB, sets the 1080x2340 panel PCDs and
  the "Nubia Z20" SMBIOS strings, and renames raphael references. Aloha's
  `SurfaceDuo1NoSb.dsc` is already parameterised on `$(TARGET_DEVICE)`, so the
  package needs no other edit. The SM8150 `PlatformMemoryMapLib` is reused: it
  already covers 4/6/8/10/12 GB (its memory-hole comments).
* **Stage 1 (fallback)** — set `TARGET_DEVICE = "xiaomi-raphael"` and
  `FDT = "raphael.dtb"` in `board.toml`; the build then only swaps raphael's DTB
  content in place.

What stage 2 still borrows from raphael: `Binaries/` and `PatchedBinaries/`,
the vendor DXE drivers (UFS, USB, buttons, display) that Aloha does not
redistribute. They may be close enough to boot. The dump showed that the Z20's
`xbl` carries a monolithic UEFI build with no per-driver `PE32` payloads, so
replacing them means finding a full Nubia firmware package with an unpacked UEFI
FD; see `docs/nx627j-live-dump.md` and `docs/aloha-device-port.md`.

## What is verified, and what is not

Verified here: Python syntax, `devices.py` import, `mkadt.py` generation of an
ADT for `nx627j`, TOML parse, workflow YAML shape; and, from the live phone, the
board FDT, the panel/touch GPIOs, the real `/memory` map, the `xbl` UEFI volume
location and the `dtbo` entry count (`docs/nx627j-live-dump.md`).

**Not verified**: EDK II build of the Aloha volume for this board, the DTB
override path on a real Z20, `fastboot boot` acceptance by the Z20 ABL, panel
bring-up, and the touch IC. Those need the phone in bootloader mode plus a built
image; treat the first run as an experiment, not a release.

## Known hardware gaps

See `docs/nx627j-live-dump.md` (the phone's own device tree). Short version: the
touch panel is a Goodix "6270" on a different SE/IRQ than raphael's GT9889, the
panel is an EW811 1080x2340 AMOLED, and USB is USB 2.0 only.
