#!/usr/bin/env python3
"""A small HFS+ reader: enough to pull files out of an iOS root.

The build server can mount the volume and run fsck over it, but this
workstation cannot, and a check that only runs on the server is not a check
of the file that is about to be flashed.  This reads the volume directly:
the volume header carries the extents of the catalog file, and the catalog
B-tree carries every file's name and where its data lives.

    from hfsplus import HFSPlusVolume
    vol = HFSPlusVolume(reader)          # reader.read(offset, length)
    data = vol.read_path('/System/Library/xpc/launchd.plist')

`reader` only has to provide read(offset, length) over the raw volume.
verify_root.SparseImage is one, and so is a plain file object.
"""
import struct
import sys

# Volume header
VH_SIG = 0x482B          # 'H+'  case-insensitive
VH_SIG_CASE = 0x4858     # 'HX'  case-sensitive
VH_SIZE = 512
VH_VOLUME_START = 1024

# Offsets inside the volume header.
VH_FILE_COUNT = 32
VH_FOLDER_COUNT = 36
VH_BLOCK_SIZE = 40
VH_TOTAL_BLOCKS = 44
VH_CATALOG_FORK = 272    # HFSPlusForkData
VH_ALLOC_FORK = 112
VH_EXTENTS_FORK = 192

# B-tree node kinds.  These are the values the HFS+ implementation uses,
# not the numbers one would guess from a textbook: the leaf node is 255.
BT_HEADER = 1
BT_LEAF = 255
BT_INDEX = 2
BT_MAP = 3

# Catalog record types.  These are the values the HFS+ implementation
# uses: 1 is a folder and 2 is a file, which is the opposite of what the
# names in Apple's headers suggest.
CAT_FOLDER = 0x0001
CAT_FILE = 0x0002
CAT_SYMLINK = 0x0003

# The root folder's parent id.
ROOT_PARENT = 2


class HFSError(Exception):
    pass


class ForkData(object):
    """An HFSPlusForkData: the extents of one fork of one file."""

    def __init__(self, raw):
        (self.logical_size, self.clump_size, self.total_blocks) = \
            struct.unpack(">QII", raw[0:16])
        self.extents = []
        for i in range(8):
            start, count = struct.unpack(">II", raw[16 + i * 8:24 + i * 8])
            if count:
                self.extents.append((start, count))

    def __repr__(self):
        return "ForkData(size=%d, extents=%s)" % (self.logical_size,
                                                   self.extents)


class HFSPlusVolume(object):
    """An HFS+ volume read through a random-access reader."""

    def __init__(self, reader, volume_start=VH_VOLUME_START):
        self.reader = reader
        self.volume_start = volume_start
        head = reader.read(volume_start, VH_SIZE)
        if len(head) < VH_SIZE:
            raise HFSError("short volume header")
        sig, self.version = struct.unpack(">HH", head[0:4])
        if sig not in (VH_SIG, VH_SIG_CASE):
            raise HFSError("not an HFS+ volume (signature %#x)" % sig)
        self.case_sensitive = (sig == VH_SIG_CASE)
        self.file_count = struct.unpack(">I", head[VH_FILE_COUNT:VH_FILE_COUNT + 4])[0]
        self.folder_count = struct.unpack(">I", head[VH_FOLDER_COUNT:VH_FOLDER_COUNT + 4])[0]
        self.block_size = struct.unpack(">I", head[VH_BLOCK_SIZE:VH_BLOCK_SIZE + 4])[0]
        self.total_blocks = struct.unpack(">I", head[VH_TOTAL_BLOCKS:VH_TOTAL_BLOCKS + 4])[0]
        self.catalog = ForkData(head[VH_CATALOG_FORK:VH_CATALOG_FORK + 80])
        self._catalog_bytes = None
        self._index = None
        self._origin = None

    # -- raw volume access ------------------------------------------------

    def read_volume(self, offset, length):
        """Read `length` bytes at `offset` inside the volume."""
        origin = self._pick_catalog_origin()
        return self.reader.read(origin + offset, length)

    # -- the catalog ------------------------------------------------------

    def catalog_bytes(self):
        if self._catalog_bytes is None:
            out = bytearray()
            for start, count in self.catalog.extents:
                out += self.read_volume(start * self.block_size,
                                        count * self.block_size)
            self._catalog_bytes = bytes(out)
        return self._catalog_bytes

    def _btree_header(self):
        """Return (node_size, first_leaf_node) from the catalog's node 0.

        The header record layout was read off this volume rather than
        assumed: treeDepth at 14, firstLeafNode at 24, nodeSize at 32
        (8192 here), maxKeyLength at 34 (516), totalNodes at 36.
        """
        data = self.catalog_bytes()
        if len(data) < 64:
            raise HFSError("catalog is too short")
        kind = data[8]
        if kind != BT_HEADER:
            raise HFSError("catalog does not start with a header node")
        first_leaf = struct.unpack(">I", data[24:28])[0]
        node_size = struct.unpack(">H", data[32:34])[0]
        if node_size == 0:
            raise HFSError("catalog node size is zero")
        return node_size, first_leaf

    def _pick_catalog_origin(self):
        """Work out where the volume's data blocks start in the reader.

        The volume header sits at byte 1024, but the allocation blocks can
        be numbered from byte 0 of the partition or from byte 1024, and
        the two differ by exactly one kilobyte.  Rather than assume, try
        both and keep the one where the catalog's first node really is a
        B-tree header node.
        """
        if self._origin is not None:
            return self._origin
        start, _count = self.catalog.extents[0]
        for origin in (0, self.volume_start):
            probe = self.reader.read(origin + start * self.block_size, 64)
            if len(probe) >= 64 and probe[8] == BT_HEADER:
                self._origin = origin
                return origin
        raise HFSError("cannot locate the catalog in the volume")

    def _catalog_index(self):
        """Map (parent_id, name) -> (record_type, file_id, data_fork)."""
        if self._index is not None:
            return self._index
        node_size, first_leaf = self._btree_header()
        data = self.catalog_bytes()
        index = {}
        node_count = len(data) // node_size
        for n in range(node_count):
            base = n * node_size
            kind = data[base + 8]
            if kind != BT_LEAF:
                continue
            nrec = struct.unpack(">H", data[base + 10:base + 12])[0]
            if nrec == 0 or nrec > 4096:
                continue
            # The record offset array sits at the end of the node and runs
            # backwards: entry 0 is the LAST record and entry nrec is the
            # first, so record i runs from offs[nrec-i] to offs[nrec-i-1].
            tail = base + node_size - 2 * (nrec + 1)
            offs = struct.unpack(">%dH" % (nrec + 1), data[tail:base + node_size])
            for i in range(nrec):
                start = offs[nrec - i]
                end = offs[nrec - i - 1]
                if end <= start or base + end > len(data):
                    continue
                rec = data[base + start:base + end]
                try:
                    key_len = struct.unpack(">H", rec[0:2])[0]
                    parent_id = struct.unpack(">I", rec[2:6])[0]
                    # The catalog key is keyLength, parentID, nameLength,
                    # name.  keyLength counts only the parentID and the
                    # name, not the nameLength field itself: a name of
                    # seven characters gives keyLength 6 + 14 = 20.
                    name_len = struct.unpack(">H", rec[6:8])[0]
                    name = rec[8:8 + name_len * 2].decode("utf-16-be", "replace")
                    if key_len != 6 + name_len * 2:
                        continue
                    # The record's data part starts on a two byte boundary
                    # after the key: keyLength(2) + parentID(4) + nameLength(2)
                    # + the name.
                    d = (8 + name_len * 2 + 1) & ~1
                    if d + 2 > len(rec):
                        continue
                    rec_type = struct.unpack(">H", rec[d:d + 2])[0]
                except (struct.error, IndexError):
                    continue
                if rec_type == CAT_FILE:
                    file_id = struct.unpack(">I", rec[d + 8:d + 12])[0]
                    # The data fork's HFSPlusForkData starts 88 bytes into
                    # the catalog file record; its extents start 16 further.
                    if len(rec) < d + 88 + 80:
                        continue
                    fork = ForkData(rec[d + 88:d + 88 + 80])
                    index[(parent_id, name)] = (CAT_FILE, file_id, fork)
                elif rec_type == CAT_FOLDER:
                    file_id = struct.unpack(">I", rec[d + 8:d + 12])[0]
                    index[(parent_id, name)] = (CAT_FOLDER, file_id, None)
        self._index = index
        return index

    def _folder_id(self, index, path_components):
        """Walk the path, returning the folder id of the directory."""
        parent = ROOT_PARENT
        for comp in path_components:
            entry = index.get((parent, comp))
            if entry is None:
                return None
            kind, file_id, _fork = entry
            if kind != CAT_FOLDER:
                return None
            parent = file_id
        return parent

    def read_path(self, path):
        """Return the bytes of one file, or None if it is not there."""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return None
        index = self._catalog_index()
        parent = self._folder_id(index, parts[:-1])
        if parent is None:
            return None
        entry = index.get((parent, parts[-1]))
        if entry is None or entry[0] != CAT_FILE:
            return None
        fork = entry[2]
        out = bytearray()
        for start, count in fork.extents:
            out += self.read_volume(start * self.block_size,
                                    count * self.block_size)
        return bytes(out[:fork.logical_size])

    def list_dir(self, path):
        """List the names of the entries in one directory."""
        parts = [p for p in path.split("/") if p]
        index = self._catalog_index()
        parent = self._folder_id(index, parts)
        if parent is None:
            return []
        names = []
        for (pid, name), entry in index.items():
            if pid == parent:
                names.append((name, entry[0]))
        names.sort()
        return names
