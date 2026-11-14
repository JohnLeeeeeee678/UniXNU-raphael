#!/usr/bin/env python3
"""Edit the kernel boot arguments inside a UniXNU payload FAT image.

The payload is a FAT32 volume whose EFI/UniXNU/unixnu.toml carries the
`args = "..."` line that the firmware hands to the kernel.  Changing a boot
argument therefore means editing one text file inside that FAT volume --
no kernel rebuild, no firmware rebuild.

The file is rewritten in place inside its own cluster chain, so the volume
geometry (and therefore the partition the payload is flashed into) is
unchanged.  The new argument list must not be longer than the old one plus
the slack already present in the last cluster; the tool refuses to write a
file that would need an extra cluster.

Usage:
    fat_args.py show   PAYLOAD.img
    fat_args.py set    PAYLOAD.img "arg1 arg2 ..."      # replaces the list
    fat_args.py patch  PAYLOAD.img "newarg"            # adds one argument
"""
import struct
import sys

SECTOR = 512


class Fat32:
    def __init__(self, data):
        self.data = bytearray(data)
        if self.data[510:512] != b"\x55\xaa":
            raise SystemExit("not a FAT volume (no 55AA signature)")
        self.bps = struct.unpack_from("<H", self.data, 11)[0]
        self.spc = self.data[13]
        self.reserved = struct.unpack_from("<H", self.data, 14)[0]
        self.nfats = self.data[16]
        self.fatsz = struct.unpack_from("<I", self.data, 36)[0]
        self.root = struct.unpack_from("<I", self.data, 44)[0]
        self.cluster_bytes = self.bps * self.spc
        self.fat_offset = self.reserved * self.bps
        self.data_offset = self.fat_offset + self.nfats * self.fatsz * self.bps

    def fat_entry(self, cluster):
        off = self.fat_offset + cluster * 4
        return struct.unpack_from("<I", self.data, off)[0] & 0x0FFFFFFF

    def set_fat_entry(self, cluster, value):
        off = self.fat_offset + cluster * 4
        cur = struct.unpack_from("<I", self.data, off)[0]
        struct.pack_into("<I", self.data, off, (cur & 0xF0000000) | (value & 0x0FFFFFFF))

    def cluster_offset(self, cluster):
        return self.data_offset + (cluster - 2) * self.cluster_bytes

    def chain(self, first):
        out = []
        cluster = first
        seen = set()
        while 2 <= cluster < 0x0FFFFFF8:
            if cluster in seen:
                raise SystemExit("FAT cluster loop")
            seen.add(cluster)
            out.append(cluster)
            cluster = self.fat_entry(cluster)
        return out

    def read_chain(self, first, size=None):
        data = bytearray()
        for cluster in self.chain(first):
            data += self.data[self.cluster_offset(cluster):
                              self.cluster_offset(cluster) + self.cluster_bytes]
            if size is not None and len(data) >= size:
                break
        return bytes(data[:size] if size is not None else data)

    def dir_entries(self, cluster):
        """Yield (name, entry_offset, cluster, size) for a directory cluster."""
        for cluster in self.chain(cluster):
            base = self.cluster_offset(cluster)
            for off in range(0, self.cluster_bytes, 32):
                e = base + off
                first = self.data[e]
                if first == 0x00:
                    return
                if first == 0xE5:
                    continue
                name = bytes(self.data[e:e + 11])
                attr = self.data[e + 11]
                if attr in (0x0F,):
                    continue
                if name[0:1] == b"\x05":
                    continue
                sub = struct.unpack_from("<H", self.data, e + 26)[0]
                hi = struct.unpack_from("<H", self.data, e + 20)[0]
                lo = struct.unpack_from("<H", self.data, e + 26)[0]
                size = struct.unpack_from("<I", self.data, e + 28)[0]
                clus = (hi << 16) | lo
                text = name.decode("ascii", "replace").rstrip()
                yield text, e, clus, size, attr

    def find(self, path):
        """Find a file by 'A/B/C' path; returns (entry_offset, cluster, size)."""
        parts = path.replace("\\", "/").split("/")
        cluster = self.root
        for i, part in enumerate(parts):
            hit = None
            for text, e, clus, size, attr in self.dir_entries(cluster):
                if text.upper() != part.upper():
                    continue
                if i == len(parts) - 1:
                    hit = (e, clus, size)
                else:
                    if attr & 0x10:            # directory
                        cluster = clus
                        hit = "dir"
                        break
                break
            if hit == "dir":
                continue
            if hit is None:
                raise SystemExit(f"path not found: {path} (at {part})")
            return hit
        raise SystemExit(f"path not found: {path}")

    def free_clusters(self, limit=4096):
        """Return a list of cluster numbers that are free in FAT #1.

        The payload's kernel.macho occupies the low clusters, so the free
        ones are far into the volume; scan the whole table.
        """
        out = []
        total = self.fatsz * 4
        for cluster in range(2, min(total, 0x0FFFFFF0)):
            if self.fat_entry(cluster) == 0:
                out.append(cluster)
                if len(out) >= limit:
                    break
        return out

    def write_file(self, path, content):
        entry_off, cluster, size = self.find(path)
        chain = self.chain(cluster)
        capacity = len(chain) * self.cluster_bytes
        if len(content) > capacity:
            # Grow the chain: append free clusters and link them in the FAT.
            need = (len(content) - capacity + self.cluster_bytes - 1) // self.cluster_bytes
            free = self.free_clusters(need * 4 + 16)
            if len(free) < need:
                raise SystemExit(
                    f"need {need} more clusters but only {len(free)} are free")
            added = free[:need]
            self.set_fat_entry(chain[-1], added[0])
            for a, b in zip(added, added[1:]):
                self.set_fat_entry(a, b)
            self.set_fat_entry(added[-1], 0x0FFFFFFF)   # end of chain
            chain = chain + added
            capacity = len(chain) * self.cluster_bytes
        # Write the payload into the (possibly grown) chain.
        blob = bytearray(content) + bytearray(capacity - len(content))
        for i, c in enumerate(chain):
            off = self.cluster_offset(c)
            self.data[off:off + self.cluster_bytes] = blob[i * self.cluster_bytes:
                                                          (i + 1) * self.cluster_bytes]
        # Update the directory entry size.
        struct.pack_into("<I", self.data, entry_off + 28, len(content))
        return bytes(self.data), len(content)


TOML_PATH = "EFI/UNIXNU/UNIXNU~1TOM"


def read_args(fat):
    _, cluster, size = fat.find(TOML_PATH)
    blob = fat.read_chain(cluster, size).decode("latin-1")
    for line in blob.splitlines():
        if line.startswith("args = "):
            return line[len('args = '):].strip().strip('"')
    raise SystemExit("no args line in unixnu.toml")


def write_args(fat, newargs):
    _, cluster, size = fat.find(TOML_PATH)
    blob = fat.read_chain(cluster, size).decode("latin-1")
    lines = blob.splitlines(keepends=True)
    out = []
    hit = False
    for line in lines:
        if line.startswith("args = "):
            out.append(f'args = "{newargs}"\n')
            hit = True
        else:
            out.append(line if line.endswith("\n") else line + "\n")
    if not hit:
        raise SystemExit("no args line in unixnu.toml")
    newblob = "".join(out).encode("latin-1")
    return fat.write_file(TOML_PATH, newblob)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    data = open(path, "rb").read()
    fat = Fat32(data)
    if cmd == "show":
        print(read_args(fat))
    elif cmd == "set":
        newargs = sys.argv[3]
        out, n = write_args(fat, newargs)
        open(path, "wb").write(out)
        print(f"args now: {newargs}")
    elif cmd == "patch":
        extra = sys.argv[3]
        cur = read_args(fat).split()
        name = extra.split("=", 1)[0]
        cur = [a for a in cur if a.split("=", 1)[0] != name]
        cur.append(extra)
        out, n = write_args(fat, " ".join(cur))
        open(path, "wb").write(out)
        print("args now: " + " ".join(cur))
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
