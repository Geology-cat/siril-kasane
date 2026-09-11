"""
統合テスト用の合成 FITS データを生成する（numpy のみ、astropy 不要）

  python tools/make_test_data.py <出力先> [--mono] [--n-light 8]

生成物:
  <出力先>/lights/   星像 + 背景 + ホットピクセル + 周辺減光。フレームごとに数ピクセルのディザ
  <出力先>/darks/    ホットピクセル + ノイズ
  <出力先>/flats/    周辺減光
  <出力先>/darkflats/ ノイズのみ（Flat と同じ露出）
OSC の場合は BAYERPAT=RGGB を付け、CFA モザイクにする。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

W, H = 480, 360
N_STARS = 60


def card(key: str, value, comment: str = "") -> bytes:
    if isinstance(value, bool):
        body = f"{key:<8}= {'T' if value else 'F':>20}"
    elif isinstance(value, int):
        body = f"{key:<8}= {value:>20d}"
    elif isinstance(value, float):
        body = f"{key:<8}= {value:>20.6f}"
    else:
        s = str(value).replace("'", "''")
        body = f"{key:<8}= '{s:<8}'"
    if comment:
        body += f" / {comment}"
    return body.ljust(80)[:80].encode("ascii")


def write_fits(path: Path, data: np.ndarray, cards: dict) -> None:
    data16 = np.clip(data, 0, 65535).astype(">u2")
    header = [
        card("SIMPLE", True),
        card("BITPIX", 16),
        card("NAXIS", 2),
        card("NAXIS1", data.shape[1]),
        card("NAXIS2", data.shape[0]),
        card("BZERO", 32768),
        card("BSCALE", 1),
    ]
    for k, v in cards.items():
        header.append(card(k, v))
    header.append(b"END".ljust(80))
    hdr = b"".join(header)
    hdr += b" " * ((2880 - len(hdr) % 2880) % 2880)
    # BZERO=32768 の符号付き表現にする
    raw = (data16.astype(np.int32) - 32768).astype(">i2").tobytes()
    raw += b"\0" * ((2880 - len(raw) % 2880) % 2880)
    path.write_bytes(hdr + raw)


def vignette() -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W]
    r = np.sqrt((x - W / 2) ** 2 + (y - H / 2) ** 2) / (W / 2)
    return 1.0 - 0.35 * r**2


def star_field(rng: np.random.Generator, dx: float, dy: float, stars: np.ndarray) -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W), dtype=np.float64)
    for sx, sy, flux, sigma in stars:
        cx, cy = sx + dx, sy + dy
        img += flux * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma**2))
    return img


def cfa_mosaic(rgb_gain: tuple[float, float, float]) -> np.ndarray:
    """RGGB の各画素に掛ける感度マップ"""
    m = np.ones((H, W))
    m[0::2, 0::2] *= rgb_gain[0]
    m[0::2, 1::2] *= rgb_gain[1]
    m[1::2, 0::2] *= rgb_gain[1]
    m[1::2, 1::2] *= rgb_gain[2]
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--mono", action="store_true")
    ap.add_argument("--n-light", type=int, default=8)
    ap.add_argument("--n-cal", type=int, default=5)
    ap.add_argument("--filter", default="")
    args = ap.parse_args()

    rng = np.random.default_rng(42)
    out: Path = args.out
    for sub in ("lights", "darks", "flats", "darkflats"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    osc = not args.mono
    common = {"GAIN": 100, "OFFSET": 50, "XBINNING": 1, "CCD-TEMP": -10.0, "INSTRUME": "SyntheticCam"}
    if osc:
        common["BAYERPAT"] = "RGGB"
    if args.filter:
        common["FILTER"] = args.filter

    bias_level = 64 * common["OFFSET"]  # 3200
    hot = rng.random((H, W)) < 0.0005
    hot_val = rng.uniform(5000, 20000, size=(H, W))
    vig = vignette()
    cfa = cfa_mosaic((0.7, 1.0, 0.6)) if osc else np.ones((H, W))
    stars = np.column_stack(
        [
            rng.uniform(20, W - 20, N_STARS),
            rng.uniform(20, H - 20, N_STARS),
            rng.uniform(2000, 30000, N_STARS),
            rng.uniform(1.4, 2.2, N_STARS),
        ]
    )
    t0 = datetime(2026, 9, 10, 14, 0, 0)

    exp_light = 30.0
    for i in range(args.n_light):
        dx, dy = rng.uniform(-6, 6), rng.uniform(-6, 6)
        sky = 800 + star_field(rng, dx, dy, stars)
        img = bias_level + (sky * vig * cfa) + np.where(hot, hot_val, 0) + rng.normal(0, 25, (H, W))
        write_fits(
            out / "lights" / f"Light_{i + 1:03d}.fit",
            img,
            {**common, "EXPTIME": exp_light, "IMAGETYP": "Light Frame",
             "DATE-OBS": (t0 + timedelta(seconds=40 * i)).strftime("%Y-%m-%dT%H:%M:%S")},
        )

    for i in range(args.n_cal):
        img = bias_level + np.where(hot, hot_val, 0) + rng.normal(0, 25, (H, W))
        write_fits(out / "darks" / f"Dark_{i + 1:03d}.fit", img,
                   {**common, "EXPTIME": exp_light, "IMAGETYP": "Dark Frame"})

    exp_flat = 2.0
    for i in range(args.n_cal):
        img = bias_level + 20000 * vig * cfa + rng.normal(0, 60, (H, W))
        write_fits(out / "flats" / f"Flat_{i + 1:03d}.fit", img,
                   {**common, "EXPTIME": exp_flat, "IMAGETYP": "Flat Frame"})
        img = bias_level + rng.normal(0, 25, (H, W))
        write_fits(out / "darkflats" / f"DarkFlat_{i + 1:03d}.fit", img,
                   {**common, "EXPTIME": exp_flat, "IMAGETYP": "Dark Flat"})

    print(f"generated: {out} ({'OSC' if osc else 'Mono'}) lights={args.n_light} cal={args.n_cal}")


if __name__ == "__main__":
    main()
