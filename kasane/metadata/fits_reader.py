"""
FITS ヘッダ読取り（純 Python 実装、astropy 不要）

FITS のヘッダは 2880 バイト単位のブロックに 80 文字のカードが並ぶだけなので、
プライマリ HDU のヘッダを読むだけなら自前で十分。ピクセルデータは読まない。
撮影ソフトごとにキーワード名が揺れるので、別名表で吸収する。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

BLOCK = 2880
CARD = 80

# キーワードの別名表（先頭から順に探す）
ALIASES: dict[str, list[str]] = {
    "exposure": ["EXPTIME", "EXPOSURE", "EXP_TIME"],
    "gain": ["GAIN", "EGAIN", "ISOSPEED", "ISO"],
    "offset": ["OFFSET", "BLKLEVEL", "BRIGHTNESS"],
    "filter": ["FILTER", "FILTER1", "FILTNAME"],
    "xbinning": ["XBINNING", "BINNING", "XBIN"],
    "temperature": ["CCD-TEMP", "CCDTEMP", "CCD_TEMP", "SENSORTEMP", "TEMPERAT"],
    "date_obs": ["DATE-OBS", "DATE_OBS", "DATE"],
    "instrument": ["INSTRUME", "CAMERA", "CAMERAID"],
    "image_type": ["IMAGETYP", "IMGTYPE", "FRAME", "FRAMETYP"],
    "bayer": ["BAYERPAT", "COLORTYP", "CFAPAT"],
    "naxis1": ["NAXIS1"],
    "naxis2": ["NAXIS2"],
    "naxis3": ["NAXIS3"],
    "naxis": ["NAXIS"],
}

# IMAGETYP の値 → 種別
IMAGE_TYPE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"dark\s*flat|flat\s*dark", re.I), "darkflat"),
    (re.compile(r"light|object|science", re.I), "light"),
    (re.compile(r"dark", re.I), "dark"),
    (re.compile(r"flat", re.I), "flat"),
    (re.compile(r"bias|zero|offset", re.I), "bias"),
]

BAYER_PATTERNS = {"RGGB", "BGGR", "GRBG", "GBRG", "RGBG", "GRGB", "GBGR", "BGRG"}


class FitsHeaderError(Exception):
    pass


def read_header(path: Path) -> dict[str, Any]:
    """プライマリ HDU のヘッダを dict にして返す（値は Python の型に変換）"""
    header: dict[str, Any] = {}
    with open(path, "rb") as f:
        first = f.read(CARD)
        if not first.startswith(b"SIMPLE"):
            raise FitsHeaderError("FITS ファイルではありません（SIMPLE カードが無い）")
        f.seek(0)
        blocks = 0
        while True:
            block = f.read(BLOCK)
            if len(block) < BLOCK:
                raise FitsHeaderError("ヘッダが途中で終わっています")
            blocks += 1
            end = False
            for i in range(0, BLOCK, CARD):
                card = block[i : i + CARD].decode("ascii", errors="replace")
                key = card[:8].strip()
                if key == "END":
                    end = True
                    break
                if not key or key in ("COMMENT", "HISTORY", "CONTINUE"):
                    continue
                if card[8:10] != "= ":
                    continue
                value = _parse_value(card[10:])
                if key not in header:
                    header[key] = value
            if end or blocks > 200:
                break
    return header


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("'"):
        # 文字列。'' はエスケープされた '
        end = 1
        buf = []
        while end < len(raw):
            c = raw[end]
            if c == "'":
                if end + 1 < len(raw) and raw[end + 1] == "'":
                    buf.append("'")
                    end += 2
                    continue
                break
            buf.append(c)
            end += 1
        return "".join(buf).strip()
    # コメントを落とす
    value = raw.split("/", 1)[0].strip()
    if value in ("T", "F"):
        return value == "T"
    try:
        if re.fullmatch(r"[+-]?\d+", value):
            return int(value)
        return float(value.replace("D", "E"))
    except ValueError:
        return value


def lookup(header: dict[str, Any], name: str) -> Any:
    for key in ALIASES[name]:
        if key in header:
            return header[key]
    return None


def normalize_image_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    for pattern, kind in IMAGE_TYPE_MAP:
        if pattern.search(text):
            return kind
    return None


def parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: 26 if ".%f" in fmt else len(text)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    return int(round(f)) if f is not None else None


def extract(header: dict[str, Any]) -> dict[str, Any]:
    """ヘッダから FrameInfo 用の正規化済み値を取り出す"""
    naxis = _to_int(lookup(header, "naxis")) or 0
    naxis3 = _to_int(lookup(header, "naxis3"))
    bayer_raw = lookup(header, "bayer")
    bayer = str(bayer_raw).strip().upper() if bayer_raw else None
    if bayer and bayer not in BAYER_PATTERNS:
        bayer = None

    # センサー判定: BAYERPAT があれば OSC。3 平面ならデベイヤー済みカラー（OSC 扱い）。
    # 単平面で BAYERPAT が無ければ mono と判定するが、確度が低いので "mono?" とせず mono にして UI で上書き可能にする
    if bayer:
        sensor = "osc"
    elif naxis == 3 and naxis3 == 3:
        sensor = "osc"
    elif naxis == 2 or (naxis == 3 and naxis3 == 1):
        sensor = "mono"
    else:
        sensor = "unknown"

    filt = lookup(header, "filter")
    filt = str(filt).strip() if filt not in (None, "") else None

    return {
        "sensor": sensor,
        "bayer_pattern": bayer,
        "exposure": _to_float(lookup(header, "exposure")),
        "iso_or_gain": _to_float(lookup(header, "gain")),
        "offset": _to_float(lookup(header, "offset")),
        "filter": filt,
        "binning": _to_int(lookup(header, "xbinning")),
        "temperature": _to_float(lookup(header, "temperature")),
        "width": _to_int(lookup(header, "naxis1")),
        "height": _to_int(lookup(header, "naxis2")),
        "date_obs": parse_date(lookup(header, "date_obs")),
        "instrument": (str(lookup(header, "instrument")).strip() or None) if lookup(header, "instrument") else None,
        "image_type": normalize_image_type(lookup(header, "image_type")),
    }
