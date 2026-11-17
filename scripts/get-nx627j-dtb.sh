#!/usr/bin/env bash
# Fetch the device tree blob for nx627j (Nubia Z20).
#
# Sources, in order:
#
#   1. inputs/nx627j.dtb        optional: your own dump of the merged tree
#                               (adb shell su -c 'cat /sys/firmware/fdt' > nx627j.dtb)
#                               or the dtbo overlay. Only needed if you want the
#                               board-level nodes; the boot chain does not.
#   1b. $NX627J_DTB_URL         optional: same file, fetched over HTTP. This is
#                               how CI gets the board tree without committing a
#                               binary: set the workflow_dispatch input dtb_url.
#   2. ./boot.img               the image we already have. Its DTB table carries
#                               the SM8150 v2 SoC tree: GIC/timer/UFS and
#                               cont_splash_region are all there, and ABL
#                               rewrites /memory at boot, so this is enough to
#                               build and boot. tools/pick-bootimg-dtb.py picks it.
#   3. raphael's DTB            last resort, same silicon, wrong board. It has
#                               raphael's panel/touch nodes, so on a Z20 the
#                               display bring-up is not expected to work; the
#                               script says so loudly.
#
# The result is written to inputs/uefi-prebuilt/nx627j.dtb, where
# build-firmware.py picks it up and build-bootimg.py reads it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/inputs/uefi-prebuilt/nx627j.dtb"
mkdir -p "$(dirname "$DEST")"

if [ -f "$DEST" ] && [ "$(wc -c < "$DEST")" -gt 1024 ]; then
  echo "nx627j.dtb already present ($(wc -c < "$DEST") bytes)"
  exit 0
fi

# 1b) CI path: fetch the board FDT from a URL instead of committing it.
if [ -n "${NX627J_DTB_URL:-}" ] && [ ! -s "$ROOT/inputs/nx627j.dtb" ]; then
  mkdir -p "$ROOT/inputs"
  echo "fetching board DTB from \$NX627J_DTB_URL"
  if curl -fsSL "$NX627J_DTB_URL" -o "$ROOT/inputs/nx627j.dtb"; then
    MAGIC=$(head -c 4 "$ROOT/inputs/nx627j.dtb" | od -An -tx1 | tr -d ' \n')
    if [ "$MAGIC" != "d00dfeed" ]; then
      echo "WARNING: \$NX627J_DTB_URL did not return an FDT (magic $MAGIC); ignoring it." >&2
      rm -f "$ROOT/inputs/nx627j.dtb"
    fi
  else
    rm -f "$ROOT/inputs/nx627j.dtb"
    echo "WARNING: could not fetch \$NX627J_DTB_URL; falling back." >&2
  fi
fi

# 1) The user's own dump.
for SRC in "$ROOT/inputs/nx627j.dtb" "$ROOT/nx627j.dtb"; do
  [ -f "$SRC" ] || continue
  SZ=$(wc -c < "$SRC")
  if [ "$SZ" -le 1024 ]; then
    echo "skip placeholder DTB: $SRC ($SZ bytes)"
    continue
  fi
  cp "$SRC" "$DEST"
  echo "copied nx627j DTB ($SZ bytes) from ${SRC#$ROOT/} -> $DEST"
  echo "sha256: $(sha256sum "$DEST" | cut -d' ' -f1)"
  exit 0
done

# 2) Extract from the boot image we already have. This is the normal path:
#    the SM8150 v2 tree carries everything the boot chain needs, and ABL
#    patches /memory at boot.
if [ -f "$ROOT/boot.img" ]; then
  if python3 "$ROOT/tools/pick-bootimg-dtb.py" "$ROOT/boot.img" "$DEST"; then
    echo "extracted the SM8150 v2 tree from boot.img -> $DEST"
    echo "NOTE: this has no nubia board nodes (they live in the dtbo overlay)." >&2
    echo "      That is fine for booting: ABL supplies /memory at runtime." >&2
    echo "      Put a merged dump at inputs/nx627j.dtb only if you want the" >&2
    echo "      board-level panel/touch nodes in the tree itself." >&2
    exit 0
  fi
fi

# 3) Last resort: raphael's real DTB from the Aloha tree.
DEV="$ROOT/uefi/Platforms/SurfaceDuo1Pkg/Device"
FALLBACK="$DEV/xiaomi-raphael/DeviceTreeBlob/Android/android-raphael.dtb"
if [ -f "$FALLBACK" ] && [ "$(wc -c < "$FALLBACK")" -gt 1024 ]; then
  cp "$FALLBACK" "$DEST"
  echo "WARNING: no nx627j DTB and no boot.img; using raphael's as a placeholder." >&2
  exit 0
fi

echo "ERROR: no DTB source found (inputs/nx627j.dtb, ./boot.img, raphael)." >&2
exit 1
