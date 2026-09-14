"""
処理に必要なディスク容量の見積もり

Siril の中間ファイル:
  変換後 (light_)   : FITS 入力は symlink（0）。RAW は 16bit CFA 1 平面
  キャリブ後 (pp_)  : 32bit。OSC で debayer するなら 3 平面
  登録後 (r_)       : pp_ と同じ × Drizzle scale^2
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..model import Project


@dataclass
class DiskEstimate:
    required_bytes: int
    free_bytes: int
    detail: dict[str, int]

    @property
    def ok(self) -> bool:
        return self.free_bytes > self.required_bytes * 1.1

    def describe(self) -> str:
        req = self.required_bytes / 1e9
        free = self.free_bytes / 1e9
        return f"推定使用量 {req:.1f} GB / 空き {free:.1f} GB"


def _pixels(project: Project) -> int:
    """1 枚あたりの画素数。サイズ不明（RAW）はフルサイズ一眼相当で見積もる"""
    for f in project.lights:
        if f.size:
            return f.size[0] * f.size[1]
    return 5600 * 3700


def estimate(project: Project, work_root: Path) -> DiskEstimate:
    px = _pixels(project)
    n_light = len(project.lights)
    n_cal = sum(len(f) for f in (project.dark_pool, project.flat_pool, project.bias_pool, project.darkflat_pool))
    s = project.settings
    bytes_per_px = 4 if s.stacking.bits32 else 2
    planes_pp = 3 if (project.is_osc and not s.drizzle.enabled) else 1
    drizzle_area = (s.drizzle.scale ** 2) if s.drizzle.enabled else 1.0

    detail: dict[str, int] = {}
    if project.is_raw:
        detail["変換後 (RAW→FITS)"] = int(n_light * px * 2)
        detail["変換後 (キャリブ用)"] = int(n_cal * px * 2)
    elif project.is_nonlinear:
        detail["変換後 (画像→FITS)"] = int(n_light * px * 2 * 3)
    detail["キャリブ後 (pp_)"] = int(n_light * px * bytes_per_px * planes_pp)
    detail["登録後 (r_)"] = int(n_light * px * bytes_per_px * planes_pp * drizzle_area)
    if planes_pp == 1 and project.is_osc:
        # Drizzle 出力は 3 平面
        detail["登録後 (r_)"] *= 3
    detail["マスター"] = int(3 * px * 4)
    required = sum(detail.values())

    try:
        probe = work_root if work_root.exists() else _nearest_existing(work_root)
        free = shutil.disk_usage(probe).free
    except OSError:
        free = 0
    return DiskEstimate(required_bytes=required, free_bytes=free, detail=detail)


def _nearest_existing(path: Path) -> Path:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return p
