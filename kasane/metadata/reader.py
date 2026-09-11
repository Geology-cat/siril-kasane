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


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in FITS_EXTENSIONS | RAW_EXTENSIONS | OTHER_EXTENSIONS


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
