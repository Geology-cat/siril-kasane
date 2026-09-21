"""
FrameInfo 抽出の入口。拡張子で FITS / RAW に振り分ける
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..model import FrameInfo, FrameKind
from . import fits_reader, raw_reader

FITS_EXTENSIONS = {".fit", ".fits", ".fts"}
# Siril（libraw）が読める代表的な RAW 拡張子
RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".raf", ".orf", ".rw2", ".pef", ".dng", ".3fr", ".iiq", ".mrw", ".x3f",
}
# FITS 圧縮 (.fz) は Siril は読めるがヘッダ位置が異なるので現状メタデータ無しで扱う
OTHER_EXTENSIONS = {".fz"}
# 非線形（ストレッチ済み / 現像済み）画像。キャリブレーション無しで位置合わせとスタックだけ行う
NONLINEAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".avif", ".bmp"}
# exifread が EXIF を読める非線形形式
_EXIF_CAPABLE = {".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".heif"}


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in FITS_EXTENSIONS | RAW_EXTENSIONS | OTHER_EXTENSIONS | NONLINEAR_EXTENSIONS


def is_nonlinear(path: Path) -> bool:
    return path.suffix.lower() in NONLINEAR_EXTENSIONS


def image_size(path: Path) -> Optional[tuple[int, int]]:
    """PNG / JPEG のヘッダから画像サイズを読む（デコードしない）。読めなければ None"""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                        continue
                    length = int.from_bytes(f.read(2), "big")
                    if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        data = f.read(5)
                        return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
                    f.seek(length - 2, 1)
    except OSError:
        return None
    return None


def read_frame(path: Path, kind: FrameKind) -> FrameInfo:
    """1 枚分のメタデータを読む。失敗しても FrameInfo は返し、error に理由を入れる"""
    path = Path(path).resolve()  # 相対パスのまま保存すると Siril 側の cwd で解決されてしまうので絶対化する
    ext = path.suffix.lower()
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    info = FrameInfo(path=path, kind=kind, file_size=size)
    try:
        if ext in FITS_EXTENSIONS:
            info.source = "fits"
            values = fits_reader.extract(fits_reader.read_header(path))
        elif ext in RAW_EXTENSIONS:
            info.source = "raw"
            values = raw_reader.extract(path)
        elif ext in NONLINEAR_EXTENSIONS:
            info.source = "image"
            values = {"sensor": "rgb", "binning": 1}
            size = image_size(path)
            if size:
                values["width"], values["height"] = size
            if ext in _EXIF_CAPABLE:
                try:
                    ex = raw_reader.extract(path)
                    values.update({k: ex[k] for k in ("exposure", "iso_or_gain", "date_obs", "instrument")})
                except Exception:
                    pass  # EXIF が無い書き出し画像は条件不明のまま扱う
        else:
            info.source = "fits"
            values = {}
            info.error = "メタデータ未対応の形式"
        for k, v in values.items():
            setattr(info, k, v)
    except Exception as e:  # noqa: BLE001 - 読めなくても一覧には出す
        info.error = f"{type(e).__name__}: {e}"
        if ext in RAW_EXTENSIONS:
            info.sensor = "osc"
            info.binning = 1
            # CR3 など exifread が読めない形式でも黒レベルは自前のパーサで読める場合がある
            try:
                from .black_level import read_black_level

                info.black_level = read_black_level(path)
            except Exception:  # noqa: BLE001
                pass
        elif ext in NONLINEAR_EXTENSIONS:
            info.source = "image"
            info.sensor = "rgb"
            info.binning = 1
            info.error = None  # メタデータが無いのは正常
    return info


def read_frames(
    paths: Iterable[Path],
    kind: FrameKind,
    progress: Optional[Callable[[int, int], None]] = None,
) -> list[FrameInfo]:
    paths = list(paths)
    out: list[FrameInfo] = []
    for i, p in enumerate(paths):
        out.append(read_frame(p, kind))
        if progress:
            progress(i + 1, len(paths))
    return out


def collect_files(paths: Iterable[Path], recursive: bool = True) -> list[Path]:
    """ファイル / フォルダの混在リストから対応形式のファイルだけを集める（名前順）"""
    found: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for q in sorted(it):
                if q.is_file() and not q.name.startswith(".") and is_supported(q):
                    found.append(q)
        elif p.is_file() and is_supported(p):
            found.append(p)
    # 重複除去（順序維持）
    seen: set[str] = set()
    unique: list[Path] = []
    for f in found:
        key = os.path.normcase(str(f.resolve()))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique
