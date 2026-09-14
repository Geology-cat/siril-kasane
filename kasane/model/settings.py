"""
処理設定のデータモデル

GUI の各タブと 1 対 1 に対応する dataclass 群。
JSON への直列化は to_dict / from_dict で行い、未知のキーは無視、欠けたキーは既定値で補う
（プリセットの前方互換のため）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, asdict
from typing import Any

# Siril の stack コマンドの方式
STACK_METHODS: dict[str, str] = {
    "rej": "Average stacking with rejection（既定）",
    "med": "Median stacking",
    "sum": "Sum stacking",
    "max": "Pixel maximum stacking",
    "min": "Pixel minimum stacking",
}

# Siril の rejection 種別（stack コマンドの 1 文字指定）
REJECTION_TYPES: dict[str, str] = {
    "w": "Winsorized Sigma Clipping",
    "s": "Sigma Clipping",
    "m": "Median Sigma Clipping",
    "l": "Linear Fit Clipping",
    "g": "GESD (Generalized Extreme Studentized Deviate)",
    "a": "MAD Clipping",
    "p": "Percentile Clipping",
    "n": "なし",
}

NORMALIZATION_TYPES: dict[str, str] = {
    "addscale": "加算 + スケーリング",
    "mulscale": "乗算 + スケーリング",
    "add": "加算",
    "mul": "乗算",
    "none": "なし",
}

WEIGHT_TYPES: dict[str, str] = {
    "none": "なし",
    "noise": "ノイズ",
    "wfwhm": "重み付き FWHM",
    "nbstars": "星数",
}

REGISTRATION_METHODS: dict[str, str] = {
    "global": "Global Star Alignment（星による位置合わせ）",
    "none": "位置合わせしない（固定三脚の軌跡合成や、位置合わせ済み画像）",
}

OUTPUT_FORMATS: dict[str, str] = {
    "fit": "FITS（32bit）",
    "tif": "TIFF（16bit）",
    "both": "FITS と TIFF の両方",
}

TRANSFORM_TYPES: dict[str, str] = {
    "homography": "Homography（既定）",
    "affine": "Affine",
    "similarity": "Similarity",
    "shift": "Shift",
}

INTERP_TYPES: dict[str, str] = {
    "default": "Siril 既定",
    "lanczos4": "Lanczos4",
    "cubic": "Cubic",
    "linear": "Linear",
    "nearest": "Nearest",
    "area": "Area",
    "none": "なし（シフトのみ）",
}

FRAMING_TYPES: dict[str, str] = {
    "current": "参照フレーム基準（既定）",
    "min": "共通領域（min）",
    "max": "全体を含む（max）",
    "cog": "重心（cog）",
}

DRIZZLE_KERNELS: dict[str, str] = {
    "square": "Square（既定）",
    "point": "Point",
    "turbo": "Turbo",
    "gaussian": "Gaussian",
    "lanczos2": "Lanczos2",
    "lanczos3": "Lanczos3",
}

DARK_OPT_MODES: dict[str, str] = {
    "off": "しない（CMOS 推奨）",
    "on": "係数を自動計算",
    "exp": "露出時間から計算",
}

FLAT_CALIB_MODES: dict[str, str] = {
    "bias": "Bias を使う",
    "darkflat": "Dark Flat を使う",
    "none": "キャリブレーションしない",
}

MIRRORX_MODES: dict[str, str] = {
    "auto": "自動（DSLR RAW のときだけ反転）",
    "on": "常に反転",
    "off": "反転しない",
}

FILTER_UNITS: dict[str, str] = {
    "k": "k 倍（中央値 + k×σ）",
    "%": "%（上位 n% を採用）",
    "abs": "実値",
}


@dataclass
class QualityFilter:
    """seqapplyreg の -filter-* オプション 1 つ分"""

    enabled: bool = False
    value: float = 3.0
    unit: str = "k"  # "k" | "%" | "abs"

    def to_arg(self, name: str) -> str | None:
        """Siril のオプション文字列に変換する。無効なら None"""
        if not self.enabled:
            return None
        if self.unit == "abs":
            return f"-filter-{name}={self.value:g}"
        return f"-filter-{name}={self.value:g}{self.unit}"


@dataclass
class CalibrationSettings:
    use_dark: bool = True
    use_flat: bool = True
    use_bias_for_light: bool = False  # Light に Bias を直接引くか（Dark に含まれるので通常 False）
    flat_calib_mode: str = "bias"  # FLAT_CALIB_MODES
    cosmetic_enabled: bool = True
    cc_sigma_low: float = 0.0  # 0 でコールドピクセル検出を無効化
    cc_sigma_high: float = 3.0
    equalize_cfa: bool = True  # OSC のみ有効
    dark_opt: str = "off"  # DARK_OPT_MODES
    # マスター作成時の rejection（枚数が少ないので Winsorized 3/3 が既定）
    master_rej_type: str = "w"
    master_sigma_low: float = 3.0
    master_sigma_high: float = 3.0


@dataclass
class RegistrationSettings:
    method: str = "global"  # REGISTRATION_METHODS
    two_pass: bool = True
    transf: str = "homography"
    minpairs: int = 10
    maxstars: int = 0  # 0 なら Siril 既定に任せる
    interp: str = "default"
    clamping: bool = True
    framing: str = "current"
    filter_wfwhm: QualityFilter = field(default_factory=lambda: QualityFilter(True, 3.0, "k"))
    filter_round: QualityFilter = field(default_factory=lambda: QualityFilter(True, 3.0, "k"))
    filter_nbstars: QualityFilter = field(default_factory=lambda: QualityFilter(False, 90.0, "%"))
    filter_fwhm: QualityFilter = field(default_factory=QualityFilter)
    filter_quality: QualityFilter = field(default_factory=QualityFilter)
    filter_bkg: QualityFilter = field(default_factory=QualityFilter)


@dataclass
class DrizzleSettings:
    enabled: bool = False
    scale: float = 1.0
    pixfrac: float = 1.0
    kernel: str = "square"
    use_flat: bool = True  # マスターフラットで入力ピクセルを重み付け


@dataclass
class StackingSettings:
    method: str = "rej"  # STACK_METHODS
    rej_type: str = "w"
    sigma_low: float = 3.0
    sigma_high: float = 3.0
    norm: str = "addscale"
    fastnorm: bool = False
    weight: str = "none"
    rgb_equal: bool = True  # OSC のみ有効
    output_norm: bool = True
    feather: int = 0
    bits32: bool = True
    rejmap: bool = False


@dataclass
class OutputSettings:
    # {target} = Light の親フォルダ名、{filter} = フィルター名（Mono）、{group} = グループ ID
    name_template: str = "result_{target}{filter_suffix}"
    format: str = "fit"  # OUTPUT_FORMATS
    mirrorx: str = "auto"  # MIRRORX_MODES
    cleanup_intermediate: bool = True
    write_ssf: bool = True
    open_result: bool = True
    setmem_ratio: float = 0.0  # 0 なら変更しない
    setcpu: int = 0  # 0 なら変更しない


@dataclass
class LibrarySettings:
    path: str = ""  # 空なら <Siril 設定フォルダ>/kasane/library
    save_masters: bool = False  # 実行後、作成したマスターをライブラリへコピーする
    auto_fallback: bool = True  # フレーム未投入の種別をライブラリから自動で補う


@dataclass
class Settings:
    calibration: CalibrationSettings = field(default_factory=CalibrationSettings)
    registration: RegistrationSettings = field(default_factory=RegistrationSettings)
    drizzle: DrizzleSettings = field(default_factory=DrizzleSettings)
    stacking: StackingSettings = field(default_factory=StackingSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    library: LibrarySettings = field(default_factory=LibrarySettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Settings":
        return _from_dict(cls, data or {})


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    """dataclass を再帰的に復元する。未知キーは無視、欠損キーは既定値"""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = f.type
        # 型注釈は文字列（from __future__ import annotations）なので名前で判定する
        nested = _NESTED_TYPES.get(str(ftype))
        if nested is not None and isinstance(value, dict):
            kwargs[f.name] = _from_dict(nested, value)
        else:
            kwargs[f.name] = value
    return cls(**kwargs)


_NESTED_TYPES: dict[str, type] = {
    "CalibrationSettings": CalibrationSettings,
    "RegistrationSettings": RegistrationSettings,
    "DrizzleSettings": DrizzleSettings,
    "StackingSettings": StackingSettings,
    "OutputSettings": OutputSettings,
    "LibrarySettings": LibrarySettings,
    "QualityFilter": QualityFilter,
}
