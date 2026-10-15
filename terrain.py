"""
Summoner's Rift ground height, read from the local League install.

The map is not flat: lanes and jungle sit near y=52, the river near y=-70,
and the bases climb to y=150+. The game's navigation grid carries a height
sample every ~25 units, so we pull that out of Map11.wad.client at startup.
"""
import os
import struct
from array import array

import zstandard

CANDIDATE_INSTALLS = [
    r"C:\Riot Games\League of Legends",
    os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\League of Legends"),
    os.path.expandvars(r"%PROGRAMFILES%\Riot Games\League of Legends"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Riot Games\League of Legends"),
]
MAP_WAD = r"Game\DATA\FINAL\Maps\Shipping\Map11.wad.client"

# xxh64 of "assets/maps/navgrid/map11/aipath_srx.aimesh_ngrid", the WAD's key for it
NAVGRID_HASH = 13236842720379347202

WAD_ENTRY = struct.Struct("<QIIIBBHQ")
NAVGRID_CELL_SIZE = 52  # one v7 navigation cell
NAVGRID_V7_TRAILER = 8 * 132  # eight unused blocks between the flags and the heights


def find_map_wad():
    for install in CANDIDATE_INSTALLS:
        path = os.path.join(install, MAP_WAD)
        if install and os.path.isfile(path):
            return path
    return None


def read_wad_entry(path, wanted_hash):
    """One file's bytes out of a v3 WAD: a 272-byte header, then 32-byte entries."""
    with open(path, "rb") as f:
        header = f.read(272)
        if header[:2] != b"RW" or header[2] != 3:
            raise ValueError(f"{path} is not a v3 WAD")
        (count,) = struct.unpack_from("<I", header, 268)
        table = f.read(count * WAD_ENTRY.size)

        for i in range(count):
            path_hash, offset, packed, size, kind, *_ = WAD_ENTRY.unpack_from(table, i * WAD_ENTRY.size)
            if path_hash != wanted_hash:
                continue
            f.seek(offset)
            data = f.read(packed)
            kind &= 0x0F
            if kind == 0:
                return data
            if kind == 3:
                return zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
            raise ValueError(f"WAD entry compression type {kind} is not handled")
    raise KeyError("navigation grid not found in the map WAD")


class Terrain:
    def __init__(self, navgrid: bytes):
        major = navgrid[0]
        if major != 7:
            raise ValueError(f"navigation grid version {major} is not handled")
        min_x, min_y, min_z, max_x, max_y, max_z = struct.unpack_from("<6f", navgrid, 3)
        _, cells_x, cells_z = struct.unpack_from("<fii", navgrid, 27)

        cells = cells_x * cells_z
        offset = 39 + cells * NAVGRID_CELL_SIZE + cells * 2 + NAVGRID_V7_TRAILER
        self.count_x, self.count_z, self.step_x, self.step_z = struct.unpack_from("<iiff", navgrid, offset)

        # the samples span the map edge to edge, so a wrong offset shows up here
        if abs((self.count_x - 1) * self.step_x - (max_x - min_x)) > self.step_x:
            raise ValueError("height samples do not cover the map - the navgrid layout changed")

        self.origin_x, self.origin_z = min_x, min_z
        self.heights = array("f")
        self.heights.frombytes(navgrid[offset + 16:offset + 16 + self.count_x * self.count_z * 4])
        self.min_height = min(self.heights)
        self.max_height = max(self.heights)

    @classmethod
    def from_install(cls):
        path = find_map_wad()
        if path is None:
            raise FileNotFoundError("Map11.wad.client not found under any known League install")
        return cls(read_wad_entry(path, NAVGRID_HASH))

    def height(self, x: float, z: float) -> float:
        """Ground y at world (x, z), bilinear between samples, clamped at the map edge."""
        column = min(max((x - self.origin_x) / self.step_x, 0.0), self.count_x - 1.001)
        row = min(max((z - self.origin_z) / self.step_z, 0.0), self.count_z - 1.001)
        c, r = int(column), int(row)
        fc, fr = column - c, row - r

        i = r * self.count_x + c
        h = self.heights
        top = h[i] + (h[i + 1] - h[i]) * fc
        bottom = h[i + self.count_x] + (h[i + self.count_x + 1] - h[i + self.count_x]) * fc
        return top + (bottom - top) * fr


class FlatTerrain:
    """Stand-in when the map can't be read: the old y=0 plane."""
    min_height = max_height = 0.0

    def height(self, x: float, z: float) -> float:
        return 0.0
