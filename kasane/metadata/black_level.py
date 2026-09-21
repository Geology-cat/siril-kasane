"""
RAW の黒レベル（オフセット）の読取り

DSLR の RAW には黒レベル（Canon 14 bit 機でおよそ 2048 ADU）が乗っている。
Dark も Bias も引かずに Flat で割ると、この一定値まで周辺ほど大きく持ち上がり、
Flat が過補正になる。Dark が無いときに Siril の -bias="=<黒レベル>" で引けるよう、
RAW から黒レベルを読む。

exifread は Canon MakerNote の ColorData を解釈しないため、TIFF 構造を自前で読む。
  - Canon (CR2 / CR3): MakerNote の ColorData (tag 0x4001) の PerChannelBlackLevel（4 値の平均）
  - DNG: RAW 本体の IFD（NewSubfileType = 0）の BlackLevel (0xC61A)
読めない機種・形式では None を返す。
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

SCAN_BYTES = 512 * 1024  # TIFF ヘッダを探す先頭のバイト数（CR3 の CMT ボックスもこの範囲にある）
MAX_TIFF = 8

# TIFF の型ごとの 1 要素のバイト数
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def canon_black_level_index(count: int, version: int) -> Optional[int]:
    """
    ColorData（int16u 配列）の中の PerChannelBlackLevel の位置。
    ExifTool 13.50 の Image::ExifTool::Canon::ColorData1〜12 の定義から抽出した。
    配列長で世代が決まり、一部は先頭の ColorDataVersion（int16s）でさらに分かれる。
    """
    if count == 796:
        return 196
    if count in (692, 674, 702, 1227, 1250, 1251, 1337, 1338, 1346):
        return {4: 692, 5: 692, 6: 715, 7: 715, 9: 719}.get(version)
    if count == 5120:
        return {-3: 264, -4: 333}.get(version)
    if count in (1273, 1275):
        return 479
    if count in (1312, 1313, 1316, 1506):
        return {10: 504, 11: 728}.get(version)
    if count in (1560, 1592, 1353, 1602):
        if version == 14:
            return 556
        if version < 14 or version == 15:
            return 778
        return None
    if count in (1816, 1820, 1824):
        return 329
    if count in (2024, 3656):
        return 343
    if count == 3973:
        return 363
    if count == 3778:
        return 363 if version != 0x41 else 383
    if count == 4528:
        return 383
    return None


def plausible_black_level(values: list[Optional[float]]) -> Optional[float]:
    """黒レベルとして妥当な値の組（ほぼ揃っていて 0 < v < 65535）なら平均を返す"""
    if not values or any(v is None or not (0 < v < 65535) for v in values):
        return None
    mean = sum(values) / len(values)  # type: ignore[arg-type]
    if max(values) - min(values) > 0.1 * mean + 16:  # type: ignore[type-var]
        return None
    return mean


class _Reader:
    def __init__(self, f, size: int):
        self.f = f
        self.size = size
        self.head = f.read(min(size, SCAN_BYTES))
        self.le = True

    def bytes(self, offset: int, count: int) -> Optional[bytes]:
        if offset < 0 or count <= 0 or offset + count > self.size:
            return None
        if offset + count <= len(self.head):
            return self.head[offset:offset + count]
        self.f.seek(offset)
        b = self.f.read(count)
        return b if len(b) == count else None

    def u16(self, offset: int) -> Optional[int]:
        b = self.bytes(offset, 2)
        return None if b is None else struct.unpack("<H" if self.le else ">H", b)[0]

    def u32(self, offset: int) -> Optional[int]:
        b = self.bytes(offset, 4)
        return None if b is None else struct.unpack("<I" if self.le else ">I", b)[0]

    def read_ifd(self, base: int, offset: Optional[int]) -> Optional[dict[int, tuple[int, int, int]]]:
        """{tag: (type, count, 値の絶対位置)}。壊れていれば None"""
        if offset is None:
            return None
        pos = base + offset
        n = self.u16(pos)
        if n is None or not 1 <= n <= 1000:
            return None
        tags: dict[int, tuple[int, int, int]] = {}
        for i in range(n):
            e = pos + 2 + 12 * i
            tag, typ, count = self.u16(e), self.u16(e + 2), self.u32(e + 4)
            if tag is None or typ not in _TYPE_SIZE or count is None:
                return None
            if _TYPE_SIZE[typ] * count <= 4:
                where = e + 8
            else:
                off = self.u32(e + 8)
                if off is None:
                    return None
                where = base + off
            tags[tag] = (typ, count, where)
        return tags

    def number(self, entry: tuple[int, int, int], index: int = 0) -> Optional[float]:
        typ, count, where = entry
        if index >= count:
            return None
        if typ == 3:
            return self.u16(where + 2 * index)
        if typ == 8:
            v = self.u16(where + 2 * index)
            return None if v is None else (v - 0x10000 if v >= 0x8000 else v)
        if typ == 4:
            return self.u32(where + 4 * index)
        if typ == 5:
            num, den = self.u32(where + 8 * index), self.u32(where + 8 * index + 4)
            return num / den if num is not None and den else None
        return None

    def text(self, entry: tuple[int, int, int]) -> str:
        typ, count, where = entry
        if typ != 2:
            return ""
        b = self.bytes(where, min(count, 256)) or b""
        return b.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def _canon_color_data(r: _Reader, entry: tuple[int, int, int]) -> Optional[float]:
    typ, count, _ = entry
    if typ not in (3, 8):
        return None
    version = r.number((8, count, entry[2]), 0)  # 先頭は int16s の ColorDataVersion
    idx = canon_black_level_index(count, int(version) if version is not None else 0)
    if idx is None or idx + 4 > count:
        return None
    return plausible_black_level([r.number((3, count, entry[2]), idx + k) for k in range(4)])


def read_black_level(path: Path) -> Optional[float]:
    """RAW の黒レベル [ADU]。読めなければ None"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            r = _Reader(f, size)
            return _scan(r)
    except OSError:
        return None


def _scan(r: _Reader) -> Optional[float]:
    make = ""
    found = 0
    head = r.head
    i = 0
    while found < MAX_TIFF:
        # "II*\0" / "MM\0*" を探す（CR2 は先頭、CR3 は CMT1〜3 ボックス、DNG は先頭）
        a = head.find(b"II*\0", i)
        b = head.find(b"MM\0*", i)
        cands = [x for x in (a, b) if x >= 0]
        if not cands:
            break
        base = min(cands)
        i = base + 1
        r.le = head[base] == 0x49
        tags = r.read_ifd(base, r.u32(base + 4))
        if tags is None:
            continue
        found += 1
        if 0x010F in tags and not make:
            make = r.text(tags[0x010F])

        # DNG: RAW 本体の IFD の BlackLevel
        ifds = [tags]
        if 0x014A in tags:
            for k in range(min(tags[0x014A][1], 8)):
                sub = r.read_ifd(base, _as_int(r.number(tags[0x014A], k)))
                if sub is not None:
                    ifds.append(sub)
        for ifd in ifds:
            if 0xC61A in ifd and (0x00FE not in ifd or r.number(ifd[0x00FE]) == 0):
                n = min(ifd[0xC61A][1], 16)
                v = plausible_black_level([r.number(ifd[0xC61A], k) for k in range(n)])
                if v is not None:
                    return v

        # Canon: IFD0 → Exif IFD → MakerNote → ColorData。CR3 の CMT3 は MakerNote そのもの
        if not make.lower().startswith("canon"):
            continue
        if 0x4001 in tags:
            v = _canon_color_data(r, tags[0x4001])
            if v is not None:
                return v
        exif = r.read_ifd(base, _as_int(r.number(tags[0x8769]))) if 0x8769 in tags else None
        if exif is not None and 0x927C in exif:
            mn = r.read_ifd(base, exif[0x927C][2] - base)
            if mn is not None and 0x4001 in mn:
                v = _canon_color_data(r, mn[0x4001])
                if v is not None:
                    return v
    return None


def _as_int(v: Optional[float]) -> Optional[int]:
    return None if v is None else int(v)
