# Linux build of `boot-nx627j.img` — 2026-11-17

First successful end-to-end build of the boot image on a plain Ubuntu box (no
macOS, no CI). This records the exact environment and the workarounds, so the
next build is reproducible.

## Host

| Item | Value |
|---|---|
| OS | Ubuntu 22.04.4 LTS |
| CPU / RAM / disk | 2 vCPU / 1 GiB / 50 GiB |
| Python | 3.10.12 (system) |
| Toolchain | clang/lld 14, nasm, iasl, mtools, EDK II BaseTools built from source |
| Access | ssh root@192.168.2.63 |

## Network workarounds (`github.com` blocked, codeload/api/raw reachable)

* `git config --global url."https://gh-proxy.com/https://github.com/".insteadOf "https://github.com/"` — needed for `git clone` of UniXNU and its submodules;
* `codeload.github.com` direct is slow (~30 KB/s), but `https://gh-proxy.com/https://codeload.github.com/...` gives ~4 MB/s. Aloha (184.5 MiB tarball, 796 MiB extracted with submodules) was fetched as tarballs; git smart-HTTP over the proxy was ~50 KB/s and unusable;
* GitHub tarballs contain submodule paths as **empty directories**; the fetcher must treat "empty" as "missing" and fetch the submodule at the gitlink SHA from the contents API;
* a nested GitLab submodule (`unit_test/cmockalib/cmocka`) cannot be fetched this way and is skipped; it is not needed for this build.

## Build steps (what actually worked)

```sh
# 1. baseline + patch
git clone --depth 1 https://github.com/JohnLeeeeeee678/UniXNU-raphael port
cd port && git am /root/0001-nx627j-unixnu-port.patch

# 2. board FDT from the phone dump
mkdir -p inputs && cp /root/nx627j-fdt.bin inputs/nx627j.dtb
bash scripts/get-nx627j-dtb.sh          # prints sha256 0605fca6…26b48

# 3. python 3.10 has no tomllib
pip3 install tomli
printf 'from tomli import *\n' > /root/pyshim/tomllib.py
export PYTHONPATH=/root/pyshim

# 4. Aloha (tarballs) + UniXNU (git clone + submodules)
#    then the three CI patches, in the CI's order:
git -C unixnu apply ../patches/unixnu-guacamole.patch
git -C uefi apply ../patches/aloha-guacamole.patch
git -C unixnu/drivers/DarwinBoot apply ../../../patches/darwinboot-guacamole.patch

# 5. local-only adaptations (do not commit)
#    - uefi is a tarball, not a repo: git init + empty commit (firmware.build reads git log for SOURCE_DATE_EPOCH)
#    - board.toml: submodules = []        (we fetched them ourselves; no gitlinks)
#    - scripts/build-firmware.py: jobs=2  (1 GiB RAM)
#    - uefi/.../nubia-nx627j/DeviceTreeBlob/Linux/linux-nx627j.dtb = "dummy\n"
#      (Aloha's FDF references both Android and Linux DTBs; the Linux one is a 6-byte placeholder in every device dir)

# 6. EDK II prebuilt dependency the CI downloads
curl -L -o /tmp/crypto.zip https://gh-proxy.com/https://github.com/microsoft/mu_crypto_release/releases/download/v1.1.3/Mu_CryptoBin_v1_1_3.zip
unzip -q -o /tmp/crypto.zip -d uefi/MU_BASECORE/CryptoPkg/Binaries/edk2-basecrypto-driver-bin_extdep

# 7. CLANGPDB tools that are on PATH only under /usr/lib/llvm-14/bin
for t in clang lld-link llvm-lib llvm-rc llvm-ar llvm-objcopy llvm-nm llvm-readobj llvm-objdump; do
  ln -sf /usr/lib/llvm-14/bin/$t /usr/local/bin/$t
done

# 8. build
python3 scripts/build-firmware.py     # -> uefi/Build/SurfaceDuo1Pkg/DEBUG_CLANGPDB/FV/SM8150_EFI.fd
python3 scripts/build-payload.py      # -> out/raphael/payload/payload.img (64 MiB)
python3 scripts/build-bootimg.py      # -> out/raphael/boot/boot-nx627j.img
```

## Kernel

No macOS here, and `inputs/` ships no kernel. For this build the prebuilt
xnu-8796 kernel from the cepheus port was used:

* `c0der88/UniXNU-cepheus` release `k8796-41323740142`,
  asset `kernel.development.cepheus`, 17,239,336 B, Mach-O magic `cffaedfe`;
* installed as `inputs/raphael/kernel.macho`;
* it is an SM8150 xnu-8796 kernel, but built by that port's CI, **not** by our
  `patches/01xx` series — so it lacks the SWEET USB CDC-ACM log, panel digest
  and GT9889/6270 touch patches. A boot with it tests the chain, not the logs.

## Result

| Artifact | Size | sha256 |
|---|---|---|
| `SM8150_EFI.fd` | 3 MiB (`FD_SIZE 0x300000`) | `9d0611fcf444d3b1…e5267` |
| `payload.img` | 67,108,864 B | `f851644f45f0df25…011592` |
| `boot-nx627j.img` | 70,840,320 B | `4d046d01153330d1a7084195e7319fcc74f9ff751b4e9594f51e9a1c68ebed31` |

Verified from `boot.json` / `payload.json` / `tools/unpack_boot.py`:

* boot header v0, page 4096, kernel `0x8000`, ramdisk `0x800000`, tags `0x100`;
* embedded DTB sha `0605fca6…26b48`, i.e. the phone's own live FDT (+32 bytes of
  `/chosen` initrd properties patched in at packing time);
* payload kernel sha `ed9a25ec…54f17`, ADT sha `21a08c4a…e878c`, kernel args as
  `board.toml`.

`hardware_tested` is false in both JSON reports: nothing has been booted yet.
