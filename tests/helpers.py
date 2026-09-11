"""テスト用のヘルパー（FrameInfo / Project の生成）"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kasane.model import FrameInfo, FrameKind, Project, Settings


def frame(
    name: str,
    kind: FrameKind,
    *,
    source: str = "fits",
    sensor: str = "osc",
    exposure: float | None = 180.0,
    gain: float | None = 100.0,
    filt: str | None = None,
    binning: int | None = 1,
    temp: float | None = -10.0,
    size: tuple[int, int] | None = (6248, 4176),
    date: datetime | None = None,
    image_type: str | None = None,
) -> FrameInfo:
    return FrameInfo(
        path=Path("/data") / kind.value / name,
        kind=kind,
        source=source,
        sensor=sensor,
        bayer_pattern="RGGB" if sensor == "osc" and source == "fits" else None,
        exposure=exposure,
        iso_or_gain=gain,
        filter=filt,
        binning=binning,
        temperature=temp,
        width=size[0] if size else None,
        height=size[1] if size else None,
        date_obs=date,
        image_type=image_type,
        file_size=50_000_000,
    )


def frames(prefix: str, kind: FrameKind, n: int, **kw) -> list[FrameInfo]:
    return [frame(f"{prefix}_{i:03d}.fit", kind, **kw) for i in range(n)]


def osc_cmos_project(n_light: int = 10, with_bias: bool = False, with_darkflat: bool = True) -> Project:
    p = Project()
    p.lights = frames("L", FrameKind.LIGHT, n_light)
    p.dark_pool = frames("D", FrameKind.DARK, 5)
    p.flat_pool = frames("F", FrameKind.FLAT, 5, exposure=2.0)
    if with_bias:
        p.bias_pool = frames("B", FrameKind.BIAS, 5, exposure=0.0)
        p.bias_mode = "frames"
    if with_darkflat:
        p.darkflat_pool = frames("DF", FrameKind.DARKFLAT, 5, exposure=2.0)
        p.darkflat_mode = "frames"
    p.settings = Settings()
    p.settings.calibration.flat_calib_mode = "darkflat" if with_darkflat else "bias"
    p.work_root = Path("/work/Kasane_test")
    p.target_name = "M31"
    return p


def dslr_project(n_light: int = 10) -> Project:
    p = Project()
    kw = dict(source="raw", gain=1600.0, filt=None, temp=None, size=None)
    p.lights = [frame(f"IMG_{i:04d}.CR2", FrameKind.LIGHT, **kw) for i in range(n_light)]
    p.dark_pool = [frame(f"IMG_D{i:04d}.CR2", FrameKind.DARK, **kw) for i in range(5)]
    p.flat_pool = [frame(f"IMG_F{i:04d}.CR2", FrameKind.FLAT, exposure=0.01, **kw) for i in range(5)]
    p.bias_mode = "constant"
    p.bias_constant = 2048
    p.settings = Settings()
    p.settings.calibration.flat_calib_mode = "bias"
    p.work_root = Path("/work/Kasane_test")
    p.target_name = "IrisNebula"
    return p


def mono_project() -> Project:
    p = Project()
    p.lights = frames("L_Ha", FrameKind.LIGHT, 6, sensor="mono", filt="Ha") + frames(
        "L_OIII", FrameKind.LIGHT, 6, sensor="mono", filt="OIII"
    )
    p.dark_pool = frames("D", FrameKind.DARK, 5, sensor="mono")
    p.flat_pool = frames("F_Ha", FrameKind.FLAT, 5, sensor="mono", filt="Ha", exposure=3.0) + frames(
        "F_OIII", FrameKind.FLAT, 5, sensor="mono", filt="OIII", exposure=5.0
    )
    p.darkflat_pool = frames("DF3", FrameKind.DARKFLAT, 5, sensor="mono", exposure=3.0) + frames(
        "DF5", FrameKind.DARKFLAT, 5, sensor="mono", exposure=5.0
    )
    p.darkflat_mode = "frames"
    p.settings = Settings()
    p.settings.calibration.flat_calib_mode = "darkflat"
    p.work_root = Path("/work/Kasane_test")
    p.target_name = "NGC7000"
    return p
