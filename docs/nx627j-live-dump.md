# nx627j live dump (TWRP recovery session, 2026-11-17)

Everything here was read off the phone itself while it sat in **TWRP recovery**
(`product:omni_NX627J`, root `adb shell`, Android kernel
`4.14.180-perf+ #1 SMP PREEMPT Sat Nov 21 01:45:05 CST 2020`, serial
`2551e42a`). Recovery mode gives root ADB without flashing anything, which is
the cheapest way to collect the device-specific inputs the port needs.

Raw dumps stay outside git (`inputs/` and `*.img` are ignored). This page is the
inventory, the hashes, and the facts extracted from them.

## What was dumped

| Partition | Node | Size | SHA-256 (device + host match) |
|---|---|---|---|
| live FDT | `/sys/firmware/fdt` | 652,509 B | `0605fca6fc4e7346d5f6c6e59c3763165e207f50c7c8ab20bd48612669726b48` |
| `xbl` | `/dev/block/sdb1` | 3,670,016 B | `fd35fd513bdff1cf4a04bd29307262a2644cb29158b88d4f5d023c9889cce77c` |
| `xblbak` | `/dev/block/sdc1` | 3,670,016 B | `4d9cbaf3aa0935a8c113f139691b3daf9c94c8d6c278aedc8eec66a4b9f6c8ae` |
| `dtbo` | `/dev/block/sde17` | 25,165,824 B | `efbf3bec4a60537aec40d4117688c988d4cd5303ea09c7260cff700812306e91` |
| `abl` | `/dev/block/sde8` | 1,048,576 B | `715e274a2c644ef5e5de181cd4ffe7845695192b7200fc99035f84e2394c1643` |

Reproduce (any recovery with root ADB):

```sh
adb shell 'cat /sys/firmware/fdt' > nx627j.dtb          # sysfs file, not dd
adb shell 'dd if=/dev/block/by-name/xbl  of=/sdcard/xbl.img  bs=4096'
adb shell 'dd if=/dev/block/by-name/dtbo of=/sdcard/dtbo.img bs=4096'
adb pull /sdcard/xbl.img .
adb pull /sdcard/dtbo.img .
```

`xbl` and `xblbak` differ. The primary slot is the newer firmware
(`NX627J_Z0_CN_WQM1R_V321`, 2022-02-24 build path inside the ELF); the backup is
an older image. Use the primary for driver extraction.

## The live FDT is the board tree

`/sys/firmware/fdt` in recovery is 652,509 bytes, root `model = MTP`,
`compatible = qcom,sm8150-mtp`, `qcom,msm-name = SM8150 V2`,
`qcom,msm-id = <0x153 0x20000>`, `qcom,board-id = <8 0>`. Unlike the SoC tree in
`boot.img`, it carries the **Nubia board nodes**, so it is the file the port
wants as `inputs/nx627j.dtb`:

* panel `qcom,mdss_dsi_ew811_1080_2340_amoled_cmd` (and the variant
  `qcom,mdss_dsi_r66455_1080_2340_amoled_cmd`), plus the secondary
  `qcom,mdss_dsi_himax_720_1520_amoled_cmd`;
* `gtx8_touch_0@5d` → `goodix_front,6270` and `gtx8_touch_1@5e` →
  `goodix_back,627`;
* the `nubia_goodix_int` / `nubia_goodix_reset` / `goodix_pwr_vdd` pinctrl
  groups, `nubia_hw_gpio_ctrl`, `nubia,keyreset`, `goodix,fingerprint`,
  `nubia,neo-battery`;
* a populated `/memory` (see below), because the bootloader already patched it.

The recovery kernel was started with
`androidboot.dtb_idx=11 androidboot.dtbo_idx=0` and
`msm_drm.dsi_display0=dsi_ew811_1080_2340_amoled_cmd_display:` — i.e. the board
overlay is entry 0 of `dtbo` and the display selection is the EW811.

## Memory: what the bootloader actually writes

`/memory/reg` from the live FDT (6 GB SKU):

| Base | Size | Meaning |
|---|---|---|
| `0x80000000` | `0x3cc00000` (972 MiB) | bank 0, holds every DT carve-out |
| `0xc0000000` | `0x80000000` (2 GiB) | lower half of the upper window |
| `0x140000000` | `0xc0000000` (3 GiB) | upper half of the upper window |

The two upper entries are adjacent, so `/proc/iomem` merges them into one
`0xc0000000-0x1ffffffff : System RAM` line. Total RAM in the map is
6,379,700,224 B ≈ 5.94 GiB; Android reports `MemTotal: 5627076 kB` after its own
carve-outs.

The port's ADT window (`dram-base 0xc0000000` + `dram-size 0xc0000000`, 3 GiB)
and Aloha's `RamPartitionDxe` upper bank (`0x180000000` + 2 GiB) together cover
exactly `0xc0000000-0x200000000`, which is the same physical DRAM the DT
describes, only split differently. No hole exists above `0xc0000000` on this
board; the only hole is `0xbcc00000-0xbfffffff`, which is already excluded.

Reserved regions (highest first): `cdsp_sec_regions` `0xa4c00000`+`0x3c00000`
(ends `0xa8800000`, which is why `/proc/iomem` resumes System RAM at
`0xa8800000`), `qseecom_region` `0x9e400000`+`0x1400000`, `disp_rdump_region`
and `cont_splash_region` both `0x9c000000`+`0x2400000`, `cdsp_regions`
`0x98900000`+`0x1400000`, `modem_region` `0x8d800000`+`0x9600000`, and the
`removed_regions` hole at `0x86200000`+`0x5500000`.

## Display

| Item | Value |
|---|---|
| Primary panel node | `qcom,mdss_dsi_ew811_1080_2340_amoled_cmd` |
| Panel string | `dsi ew811 1080 2340 amoled cmd panel` |
| Timing | 1080x2340 @ 60 Hz, command mode, DSC (slice 480x60, 8 bit/px) |
| DRM mode (live) | `1080x2340x60x67392` on `card0-DSI-1` |
| TE GPIO | `&tlmm 8` |
| Reset GPIO | `&tlmm 6` |
| Mode-select GPIO | `&tlmm 7` |
| Front VCI 3V3 GPIO | `&tlmm 130` |
| Front panel F-FD GPIO | `&tlmm 49` |
| Supply | `vddio` 1.8 V (`0x1b7740` uV), enable load `0xf230` uA |
| Framebuffer | `cont_splash_region` `0x9c000000` + `0x2400000` (36 MiB) |
| Secondary panel | `dsi himax 720 1520 amoled cmd panel`, `720x1520x60x77702` on `card0-DSI-2` |

## Touch (the driver gap)

Front touch is alive in recovery — `front_touch` on GPIO 122 shows 69
interrupts in `/proc/interrupts` — and `/sys/bus/i2c/devices/5-005d/name` reads
`6270`. Confirmed values:

| Item | Front (use this) | Back (ignore) |
|---|---|---|
| Compatible | `goodix_front,6270` | `goodix_back,627` |
| I2C node | `/soc/i2c@0xc80000/gtx8_touch_0@5d` (I2C SE17, Linux bus `i2c-5`) | `/soc/i2c@884000/gtx8_touch_1@5e` (bus `i2c-1`) |
| Address | `0x5d` | `0x5e` |
| IRQ | `&tlmm 122`, cell flags `0x2800` (`goodix,irq-flags = <2>`, falling edge) | `&tlmm 58` |
| Reset | `&tlmm 54` | `&tlmm 53` |
| Power | `&tlmm 37` | same rail |
| Slots / range | 10, 1080x2340, w/p max 512 | 720x1520 |
| Power timing | on 30000 us, off 5000 us | — |
| Pen | `goodix,pen-enable` present | — |

## `xbl`: where the Z20's own UEFI lives — and why drivers do not fall out

`xbl` is an ELF64 (`aa64`) file whose program header 11 maps **2.25 MiB
(`0x240000`) at `0x9fc00000`** — the `UEFI FD` region. Strings confirm a
Qualcomm UEFI build (`1.2.8.f-QC-UEFI`, `UEFI DXE`, `QcomPkg`,
`DisplayDxe`, `BootDisplay.c`, `DSI_Display_SetProperty`,
`0x9C000000, 0x02400000, "Display Reserved"`) and the firmware build path
`/home/sdb/nrom/NX627J_Z0_CN_WQM1R_V321/20220224143056/modem/boot_images/Build/...`.

Walking that region as a UEFI volume gives a valid `_FVH` header
(`FvLength 0x240000`, FFS2 GUID, revision 2, 512-byte blocks) but **zero FFS
files**: after the 0x48-byte header the volume is erased (`0xFF`) except for
scattered runs, and a scan of the whole 3.5 MiB `xbl` finds **no `MZ`/`PE32`
image at all**. In other words this XBL is a monolithic firmware build — the DXE
core and its drivers are linked into the image, not shipped as separate FFS
files the way `UEFIReader` expects.

Consequence for the port: the "extract the Z20's own DXE drivers from `xbl`"
step in `docs/aloha-device-port.md` cannot be done on this device as written.
Unless a full Nubia firmware package with an unpacked UEFI FD turns up, Aloha
keeps raphael's `Binaries/`, and the Z20-specific behaviour has to come from the
DTB, the ADT and the platform libraries instead.

Other UEFI-ish partitions were checked as well: `imagefv` (2 MiB, ELF wrapping a
64 KiB FV that holds one `FV_IMAGE` file) and `uefisecapp` (2 MiB, ELF, no FV).
Neither carries per-driver PE32 payloads.

## `dtbo`: 23 board overlays, entry 0 selected

`dtbo.img` starts with the standard `dt_table_header`
(magic `0xd7b7ab1e`, header 32 B, entry 32 B, `dt_entry_count = 23`,
`dt_entries_offset = 32`, page 4096) and holds 3,610,035 bytes of overlays.
Every entry has `id = 0` / `rev = 0`; entry 0 is 42,613 bytes and is the one the
bootloader applied (`androidboot.dtbo_idx=0`). 23 overlays is the usual
Nubia/Red Magic PCB-variant fan-out; only entry 0 matches this board.

## Buttons / PMIC

The live tree keeps `nubia,keyreset` and `qcom,pm8150b@2/neo,battery`
(`nubia,neo-battery`); the key handling itself is in the PM8150 PON block, as
the live tree shows.

## What this does and does not prove

Proved: the board DT, panel selection and timing, touch bus/GPIOs, the real
`/memory` map, the `xbl` UEFI volume location, and the `dtbo` layout.

Not proved: that the Z20 ABL accepts `fastboot boot` at all. `abl.img` is a
1 MiB ELF32 with no readable `fastboot` strings (its command table is not plain
text), so the answer only comes from `fastboot getvar all` / an actual
`fastboot boot` in bootloader mode.

Also not available: per-driver PE32 DXE binaries. See the `xbl` section — this
firmware build is monolithic.
