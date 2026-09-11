"""
作業ディレクトリの生成と入力ファイルのステージング（symlink / コピー）

構造:
  <work>/
    project.json
    commands.ssf
    input/
      lights/<gid>/      ← Light グループごと
      darks/<mid>/       ← マスター素材ごと
      flats/<mid>/
      biases/<mid>/
      darkflats/<mid>/
    process/
      <gid>/             ← Light の変換・中間シーケンス
      m_<mid>/           ← マスター作成の中間
    masters/             ← 作成 / 指定したマスター（指定は symlink）
    output/
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .model import FrameInfo, FrameKind

INPUT_SUBDIR = {
    FrameKind.LIGHT: "lights",
    FrameKind.DARK: "darks",
    FrameKind.FLAT: "flats",
    FrameKind.BIAS: "biases",
    FrameKind.DARKFLAT: "darkflats",
}


@dataclass
class WorkDirs:
    root: Path
    input: Path = field(init=False)
    process: Path = field(init=False)
    masters: Path = field(init=False)
    output: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.input = self.root / "input"
        self.process = self.root / "process"
        self.masters = self.root / "masters"
        self.output = self.root / "output"

    def create(self) -> None:
        for d in (self.input, self.process, self.masters, self.output):
            d.mkdir(parents=True, exist_ok=True)

    def input_dir(self, kind: FrameKind, ident: str) -> Path:
        return self.input / INPUT_SUBDIR[kind] / ident

    def process_dir(self, ident: str) -> Path:
        return self.process / ident

    @property
    def ssf_path(self) -> Path:
        return self.root / "commands.ssf"

    @property
    def project_path(self) -> Path:
        return self.root / "project.json"

    @property
    def log_path(self) -> Path:
        return self.root / "log.txt"


def new_work_root(base: Path, stamp: Optional[datetime] = None) -> Path:
    stamp = stamp or datetime.now()
    return Path(base) / f"Kasane_{stamp:%Y%m%d_%H%M%S}"


@dataclass
class StageResult:
    linked: int = 0
    copied: int = 0
    bytes_copied: int = 0

    def describe(self) -> str:
        s = f"リンク {self.linked} 件"
        if self.copied:
            s += f"、コピー {self.copied} 件（{self.bytes_copied / 1e9:.2f} GB）"
        return s


def stage_frames(
    frames: list[FrameInfo],
    dest_dir: Path,
    result: Optional[StageResult] = None,
    log: Optional[Callable[[str], None]] = None,
) -> StageResult:
    """
    frames を dest_dir に連番付きの symlink として配置する。
    symlink が張れない（exFAT 等）場合はコピーにフォールバックする。
    連番プレフィックスで Siril の convert の順序（名前順）を元の順序に揃える。
    """
    result = result or StageResult()
    dest_dir.mkdir(parents=True, exist_ok=True)
    width = max(4, len(str(len(frames))))
    for i, f in enumerate(frames, start=1):
        src = Path(f.path).resolve()
        name = f"{i:0{width}d}_{_safe_name(src.name)}"
        dst = dest_dir / name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        try:
            os.symlink(src, dst)
            result.linked += 1
        except (OSError, NotImplementedError) as e:
            if log:
                log(f"symlink 失敗のためコピーします: {src.name} ({e})")
            shutil.copy2(src, dst)
            result.copied += 1
            result.bytes_copied += f.file_size
    return result


def stage_master(master_path: Path, masters_dir: Path, name: str) -> Path:
    """既存マスター FITS を masters/ に symlink（不可ならコピー）し、その配置先を返す"""
    masters_dir.mkdir(parents=True, exist_ok=True)
    src = Path(master_path).resolve()
    dst = masters_dir / f"{name}{src.suffix.lower() if src.suffix else '.fit'}"
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError):
        shutil.copy2(src, dst)
    return dst


def cleanup_intermediate(work: WorkDirs, keep_masters: bool = True, log: Optional[Callable[[str], None]] = None) -> int:
    """process/ 以下の中間ファイルを削除し、解放したバイト数を返す"""
    freed = 0
    if work.process.exists():
        for root, _dirs, files in os.walk(work.process):
            for name in files:
                try:
                    freed += (Path(root) / name).stat().st_size
                except OSError:
                    pass
        shutil.rmtree(work.process, ignore_errors=True)
        if log:
            log(f"中間ファイルを削除しました（{freed / 1e9:.2f} GB）")
    if not keep_masters and work.masters.exists():
        shutil.rmtree(work.masters, ignore_errors=True)
    # 入力の symlink はサイズを持たないが、コピーだった場合に備えて削除する
    if work.input.exists():
        shutil.rmtree(work.input, ignore_errors=True)
    return freed


def _safe_name(name: str) -> str:
    bad = ' <>:"|?*'
    return "".join("_" if c in bad else c for c in name)
