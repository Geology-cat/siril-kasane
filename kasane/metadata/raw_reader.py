"""
DSLR RAW（CR2 / NEF / ARW など）の EXIF 読取り

exifread（純 Python）を使う。CR3 は ISOBMFF 形式で exifread が対応していないため、
読めない場合はメタデータ無し（露出・ISO は None）として扱い、変換後に Siril の seqheader で補完する。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def read_exif(path: Path) -> dict[str, Any]:
    try:
        import exifread  # type: ignore
    except ImportError as e:  # pragma: no cover - ensure_installed で導入されるはず
        raise RuntimeError("exifread が見つかりません") from e

    with open(path, "rb") as f:
        tags = exifread.process_file(f, details=False)
    return tags


def _ratio_to_float(value: Any) -> Optional[float]:
    try:
        v = value.values[0] if hasattr(value, "values") else value
        if hasattr(v, "num") and hasattr(v, "den"):
            return float(v.num) / float(v.den) if v.den else None
        return float(v)
    except Exception:
        return None


def _first_int(value: Any) -> Optional[int]:
    try:
        v = value.values[0] if hasattr(value, "values") else value
        return int(v)
    except Exception:
        return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        s = str(value).strip()
        return s or None
    except Exception:
        return None


def _date(value: Any) -> Optional[datetime]:
    s = _text(value)
    if not s:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def extract(path: Path) -> dict[str, Any]:
    """FrameInfo 用の正規化済み値。読めない項目は None"""
    tags = read_exif(path)

    def get(*names: str) -> Any:
        for n in names:
            if n in tags:
                return tags[n]
        return None

    exposure = _ratio_to_float(get("EXIF ExposureTime", "Image ExposureTime"))
    iso = _first_int(get("EXIF ISOSpeedRatings", "Image ISOSpeedRatings", "MakerNote ISOSpeed"))
    model = _text(get("Image Model"))
    date = _date(get("EXIF DateTimeOriginal", "Image DateTime"))

    # 画像サイズは EXIF の値がプレビュー寸法のことがあるので、グループ化には使わない（None）
    return {
        "sensor": "osc",  # DSLR は常に CFA
        "bayer_pattern": None,  # libraw に任せる
        "exposure": exposure,
        "iso_or_gain": float(iso) if iso is not None else None,
        "offset": None,
        "filter": None,
        "binning": 1,
        "temperature": None,
        "width": None,
        "height": None,
        "date_obs": date,
        "instrument": model,
        "image_type": None,  # RAW には種別が無い
    }
