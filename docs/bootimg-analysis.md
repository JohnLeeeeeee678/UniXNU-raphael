# The Z20 `boot.img` — what is inside

Parsed with `tools/unpack_boot.py` and `tools/fdt_tool.py` from the image in
`nx627j-port/boot.img` (96 MiB,
`sha256 98ec02457e6b2a778e361b4ad0094f72552481aaaab42bdbebe84084657e59f5`;
`boot.json` holds the parsed header after unpacking).

## Header (Android boot image v2)

| Field | Value |
|---|---|
| magic / header version | `ANDROID!` / **2** |
| page size | **4096** |
| kernel | 37,283,856 bytes at `0x8000` (file offset `0x1000`) |
| ramdisk | 399,368 bytes at `0x0` (file offset `0x2390000`) |
| second | 0 |
| tags address | `0x100` |
| DTB | 4,211,082 bytes, addr `0x1f00000`, file offset `0x23f2000` |
| `recovery_dtbo_size` | 0 |
| `header_size` | 1660 |
| cmdline | `... androidboot.selinux=permissive buildvariant=userdebug` |

`header_size = 1660` is the v2 layout, matching `dtb_size/dtb_addr` at
1648/1652.

## Kernel

* ARM64 `Image` (magic `ARMd` at `0x38`, `text_offset 0x80000`), **not** gzip;
* `Linux version 4.14.180-perf+ (nubia@swlab-2t194)`, clang 10.0.6 — a Nubia
  build, not a generic GSI kernel;
* contains `nx627j` strings (driver/board names).

## Ramdisk

Plain `newc` cpio with four entries: `init`, `.backup`, `.backup/.magisk`,
`TRAILER!!!`. That is a **Magisk-patched minimal ramdisk**, not the stock
Android initrd. Do not treat this image as a pristine factory boot.

## Device tree table (15 FDTs)

| # | Model | Compatible |
|---|---|---|
| 0 | APQ 8016 SBC | `qcom,apq8016-sbc` |
| 1 | DB820c | `arrow,apq8096-db820c` |
| 2 | IPQ8074-HK01 | `qcom,ipq8074-hk01` |
| 3 | MSM 8916 MTP | `qcom,msm8916-mtp` |
| 4 | LG Nexus 5X | `lg,bullhead` |
| 5 | Huawei Nexus 6P | `huawei,angler` |
| 6 | MSM 8996 MTP | `qcom,msm8996-mtp` |
| 7 | SA8155 v2 | `qcom,sa8155` |
| 8 | SA8155 | `qcom,sa8155` |
| 9 | SA8155P v2 | `qcom,sa8155p` |
| 10 | SA8155P | `qcom,sa8155p` |
| 11 | **SM8150 v2** | `qcom,sm8150` (msm-id `0x153/0x20000`) |
| 12 | SM8150 v1 | `qcom,sm8150` (msm-id `0x153/0x10000`) |
| 13 | SM8150P v2 | `qcom,sm8150p` (msm-id `0x169/0x20000`) |
| 14 | SM8150P v1 | `qcom,sm8150p` (msm-id `0x169/0x10000`) |

**No nubia/NX627J board tree is present.** On this device the board DT — the
one carrying `/memory`, `qcom,board-id`, the EW811 panel nodes and the nubia
touch — is applied from the **`dtbo` partition** (`recovery_dtbo_size` is 0, so
it is not in `boot.img` either).

## What the SM8150 v2 entry confirms

| Fact | Value |
|---|---|
| GIC distributor | `0x17a00000` + `0x10000` |
| GIC redistributor | `0x17a60000` + `0x100000` |
| arch timer | 19.2 MHz (`0x124f800`) |
| UFS host | `0x1d84000` + `0x2500` (ICE `0x1d90000`) |
| `cont_splash_region` | `0x9c000000` + `0x2400000` (36 MiB) |
| `/memory` | `0x0 0x0` — patched by the bootloader, unusable here |

These are the values now used by `scripts/devices.py` (`gicd`, `gicr`,
`timebase`, `ufs`, `fb`). The board-level nodes are not in this image, but they
have since been read off the phone: `docs/nx627j-live-dump.md` describes the
652,509-byte merged FDT from TWRP recovery (EW811 panel, Goodix 6270, a
populated `/memory`) and the 23-entry `dtbo` overlay table. That dump is what
`inputs/nx627j.dtb` should contain.
