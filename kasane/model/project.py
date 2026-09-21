"""
プロジェクトのデータモデル（フレーム情報・グループ・マスター指定）

Light はグループ（露出 × ISO/Gain × Filter × Binning × 画像サイズ）単位で保持し、
各グループに Dark / Flat / Bias / Dark Flat の割当て（MasterSource）を持たせる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .settings import Settings


class FrameKind(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    FLAT = "flat"
    BIAS = "bias"
    DARKFLAT = "darkflat"

    @property
    def label(self) -> str:
        return _KIND_LABELS[self]


_KIND_LABELS = {
    FrameKind.LIGHT: "Light",
    FrameKind.DARK: "Dark",
    FrameKind.FLAT: "Flat",
    FrameKind.BIAS: "Bias",
    FrameKind.DARKFLAT: "Dark Flat",
}

# Siril の convert で使うシーケンス名
SEQ_BASENAME = {
    FrameKind.LIGHT: "light",
    FrameKind.DARK: "dark",
    FrameKind.FLAT: "flat",
    FrameKind.BIAS: "bias",
    FrameKind.DARKFLAT: "darkflat",
}


@dataclass
class FrameInfo:
    """入力画像 1 枚のメタデータ"""

    path: Path
    kind: FrameKind
    source: str = "fits"  # "raw" | "fits" | "image"（非線形: JPEG / PNG / TIFF）
    sensor: str = "unknown"  # "osc" | "mono" | "rgb"（非線形画像） | "unknown"
    bayer_pattern: Optional[str] = None
    exposure: Optional[float] = None  # 秒
    iso_or_gain: Optional[float] = None  # DSLR: ISO、CMOS: GAIN
    offset: Optional[float] = None
    filter: Optional[str] = None
    binning: Optional[int] = None
    temperature: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    date_obs: Optional[datetime] = None
    instrument: Optional[str] = None
    image_type: Optional[str] = None  # FITS の IMAGETYP を正規化したもの（light/dark/flat/bias/darkflat）
    black_level: Optional[float] = None  # RAW の黒レベル [ADU]（Canon ColorData / DNG BlackLevel）。Dark が無いときの Bias に使う
    file_size: int = 0
    session_key: Optional[str] = None
    error: Optional[str] = None  # メタデータ読取り失敗の理由

    @property
    def size(self) -> Optional[tuple[int, int]]:
        if self.width and self.height:
            return (self.width, self.height)
        return None

    @property
    def name(self) -> str:
        return self.path.name

    def summary(self) -> str:
        """一覧表示用の短い説明"""
        parts = []
        if self.exposure is not None:
            parts.append(f"{self.exposure:g}s")
        if self.iso_or_gain is not None:
            parts.append(("ISO" if self.source == "raw" else "Gain") + f"{self.iso_or_gain:g}")
        if self.filter:
            parts.append(self.filter)
        if self.binning:
            parts.append(f"{self.binning}x{self.binning}")
        if self.temperature is not None:
            parts.append(f"{self.temperature:.1f}℃")
        if self.date_obs:
            parts.append(self.date_obs.strftime("%Y-%m-%d %H:%M"))
        return "  ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        d["kind"] = self.kind.value
        d["date_obs"] = self.date_obs.isoformat() if self.date_obs else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FrameInfo":
        d = dict(d)
        d["path"] = Path(d["path"])
        d["kind"] = FrameKind(d["kind"])
        if d.get("date_obs"):
            d["date_obs"] = datetime.fromisoformat(d["date_obs"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass(frozen=True)
class GroupKey:
    """Light のグループ化キー"""

    exposure: Optional[float]
    iso_or_gain: Optional[float]
    filter: Optional[str]
    binning: Optional[int]
    size: Optional[tuple[int, int]]

    def label(self, source: str = "fits") -> str:
        parts = []
        parts.append(f"{self.exposure:g}s" if self.exposure is not None else "露出不明")
        if self.iso_or_gain is not None:
            parts.append(("ISO" if source == "raw" else "Gain") + f"{self.iso_or_gain:g}")
        if self.filter:
            parts.append(self.filter)
        if self.binning:
            parts.append(f"{self.binning}x{self.binning}")
        if self.size:
            parts.append(f"{self.size[0]}x{self.size[1]}")
        return " / ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposure": self.exposure,
            "iso_or_gain": self.iso_or_gain,
            "filter": self.filter,
            "binning": self.binning,
            "size": list(self.size) if self.size else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GroupKey":
        size = d.get("size")
        return cls(
            exposure=d.get("exposure"),
            iso_or_gain=d.get("iso_or_gain"),
            filter=d.get("filter"),
            binning=d.get("binning"),
            size=tuple(size) if size else None,
        )


@dataclass
class MasterSource:
    """
    マスターフレームの供給方法

    mode:
      frames         : frames からマスターを作る
      master_file    : 既存のマスター FITS を使う
      constant       : 固定値（Bias のみ。例 2048）
      offset_keyword : FITS の OFFSET キーワードから 64*$OFFSET（Bias のみ、CMOS 向け）
      none           : 使わない
    """

    mode: str = "none"
    frames: list[FrameInfo] = field(default_factory=list)
    master_path: Optional[Path] = None
    constant: Optional[float] = None
    auto: bool = True  # 自動マッチの結果か（False なら手動指定）
    note: str = ""  # マッチングの説明 / 警告

    @property
    def is_available(self) -> bool:
        if self.mode == "frames":
            return len(self.frames) > 0
        if self.mode == "master_file":
            return self.master_path is not None
        if self.mode in ("constant", "offset_keyword"):
            return True
        return False

    def describe(self) -> str:
        if self.mode == "frames":
            return f"フレーム {len(self.frames)} 枚" + (f"（{self.note}）" if self.note else "")
        if self.mode == "master_file":
            return f"マスター: {self.master_path.name if self.master_path else '未指定'}"
        if self.mode == "constant":
            return f"固定値 {self.constant:g}" if self.constant is not None else "固定値（未設定）"
        if self.mode == "offset_keyword":
            return "64 × $OFFSET"
        return "なし"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "frames": [f.to_dict() for f in self.frames],
            "master_path": str(self.master_path) if self.master_path else None,
            "constant": self.constant,
            "auto": self.auto,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MasterSource":
        return cls(
            mode=d.get("mode", "none"),
            frames=[FrameInfo.from_dict(f) for f in d.get("frames", [])],
            master_path=Path(d["master_path"]) if d.get("master_path") else None,
            constant=d.get("constant"),
            auto=d.get("auto", True),
            note=d.get("note", ""),
        )


@dataclass
class LightGroup:
    """同一条件の Light の集合と、それに対応するマスターの割当て"""

    group_id: str  # 作業ディレクトリ名に使う（例 g01）
    key: GroupKey
    frames: list[FrameInfo]
    session: Optional[str] = None  # セッションキー（フォルダのパス or 日付）。同じ key で session 違いは merge して 1 本にスタックする
    dark: MasterSource = field(default_factory=MasterSource)
    flat: MasterSource = field(default_factory=MasterSource)
    bias: MasterSource = field(default_factory=MasterSource)
    darkflat: MasterSource = field(default_factory=MasterSource)

    @property
    def source(self) -> str:
        return self.frames[0].source if self.frames else "fits"

    @property
    def session_label(self) -> str:
        return session_label(self.session)

    @property
    def label(self) -> str:
        base = self.key.label(self.source)
        return f"[{self.session_label}] {base}" if self.session else base

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "key": self.key.to_dict(),
            "session": self.session,
            "frames": [f.to_dict() for f in self.frames],
            "dark": self.dark.to_dict(),
            "flat": self.flat.to_dict(),
            "bias": self.bias.to_dict(),
            "darkflat": self.darkflat.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LightGroup":
        return cls(
            group_id=d["group_id"],
            key=GroupKey.from_dict(d["key"]),
            frames=[FrameInfo.from_dict(f) for f in d.get("frames", [])],
            session=d.get("session"),
            dark=MasterSource.from_dict(d.get("dark", {})),
            flat=MasterSource.from_dict(d.get("flat", {})),
            bias=MasterSource.from_dict(d.get("bias", {})),
            darkflat=MasterSource.from_dict(d.get("darkflat", {})),
        )


@dataclass
class Project:
    """GUI の状態そのもの。JSON に保存して復元できる"""

    SCHEMA_VERSION = 1

    sensor_override: str = "auto"  # "auto" | "osc" | "mono"
    session_mode: str = "auto"  # "auto" | "folder" | "date" | "none"（grouping.SESSION_MODES）
    lights: list[FrameInfo] = field(default_factory=list)
    dark_pool: list[FrameInfo] = field(default_factory=list)
    flat_pool: list[FrameInfo] = field(default_factory=list)
    bias_pool: list[FrameInfo] = field(default_factory=list)
    darkflat_pool: list[FrameInfo] = field(default_factory=list)
    # 各種別の供給方法（グローバル）。"frames" のときはプールから自動マッチする
    dark_mode: str = "frames"  # frames | master_file | library | none
    flat_mode: str = "frames"  # frames | master_file | library | none
    bias_mode: str = "none"  # frames | master_file | library | constant | offset_keyword | none
    darkflat_mode: str = "none"  # frames | master_file | library | none
    dark_master_path: Optional[Path] = None
    flat_master_path: Optional[Path] = None
    bias_master_path: Optional[Path] = None
    darkflat_master_path: Optional[Path] = None
    bias_constant: float = 2048.0
    # グループ化の結果（grouping.build_groups で再計算する）
    groups: list[LightGroup] = field(default_factory=list)
    # グループごとの手動上書き {group_id: {"dark": MasterSource, ...}}
    overrides: dict[str, dict[str, MasterSource]] = field(default_factory=dict)
    work_root: Optional[Path] = None
    target_name: str = ""  # 空なら Light の親フォルダ名から推定
    settings: Settings = field(default_factory=Settings)

    # ---- 派生情報 ----------------------------------------------------------

    def pool(self, kind: FrameKind) -> list[FrameInfo]:
        return {
            FrameKind.LIGHT: self.lights,
            FrameKind.DARK: self.dark_pool,
            FrameKind.FLAT: self.flat_pool,
            FrameKind.BIAS: self.bias_pool,
            FrameKind.DARKFLAT: self.darkflat_pool,
        }[kind]

    def all_frames(self) -> list[FrameInfo]:
        return self.lights + self.dark_pool + self.flat_pool + self.bias_pool + self.darkflat_pool

    @property
    def is_nonlinear(self) -> bool:
        """Light が非線形画像（JPEG / PNG / TIFF）かどうか（多数決）。キャリブレーションは行わない"""
        if not self.lights:
            return False
        n = sum(1 for f in self.lights if f.source == "image")
        return n * 2 > len(self.lights)

    def detected_sensor(self) -> str:
        """Light のメタデータから判定したセンサー種別（多数決）"""
        if self.is_nonlinear:
            return "rgb"
        votes: dict[str, int] = {}
        for f in self.lights:
            votes[f.sensor] = votes.get(f.sensor, 0) + 1
        for s in ("osc", "mono"):
            if votes.get(s, 0) > 0 and votes.get(s, 0) >= votes.get("unknown", 0):
                # osc と mono が混在している場合は多い方
                other = "mono" if s == "osc" else "osc"
                if votes.get(s, 0) >= votes.get(other, 0):
                    return s
        return "unknown"

    @property
    def sensor(self) -> str:
        """実際に処理で使うセンサー種別。非線形画像は常に rgb（CFA 処理を行わない）"""
        if self.is_nonlinear:
            return "rgb"
        if self.sensor_override in ("osc", "mono"):
            return self.sensor_override
        return self.detected_sensor()

    @property
    def is_osc(self) -> bool:
        return self.sensor == "osc"

    @property
    def is_raw(self) -> bool:
        """Light が DSLR RAW かどうか（多数決）"""
        if not self.lights:
            return False
        raw = sum(1 for f in self.lights if f.source == "raw")
        return raw * 2 >= len(self.lights)

    def light_folder(self) -> Optional[Path]:
        """Light のフォルダ（lights / raw などの汎用名なら 1 つ上）"""
        if not self.lights:
            return None
        folder = self.lights[0].path.parent
        if folder.name.lower() in ("lights", "light", "raw", "fits"):
            folder = folder.parent
        return folder

    def effective_work_root(self) -> Optional[Path]:
        """作業フォルダ（この下に Kasane_日時/ を作る）。未指定なら Light のフォルダ内の output/"""
        if self.work_root is not None:
            return self.work_root
        folder = self.light_folder()
        return folder / "output" if folder is not None else None

    def effective_target_name(self) -> str:
        if self.target_name.strip():
            return _sanitize(self.target_name.strip())
        folder = self.light_folder()
        if folder is not None:
            return _sanitize(folder.name) or "result"
        return "result"

    # ---- 直列化 --------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "sensor_override": self.sensor_override,
            "session_mode": self.session_mode,
            "lights": [f.to_dict() for f in self.lights],
            "dark_pool": [f.to_dict() for f in self.dark_pool],
            "flat_pool": [f.to_dict() for f in self.flat_pool],
            "bias_pool": [f.to_dict() for f in self.bias_pool],
            "darkflat_pool": [f.to_dict() for f in self.darkflat_pool],
            "dark_mode": self.dark_mode,
            "flat_mode": self.flat_mode,
            "bias_mode": self.bias_mode,
            "darkflat_mode": self.darkflat_mode,
            "dark_master_path": str(self.dark_master_path) if self.dark_master_path else None,
            "flat_master_path": str(self.flat_master_path) if self.flat_master_path else None,
            "bias_master_path": str(self.bias_master_path) if self.bias_master_path else None,
            "darkflat_master_path": str(self.darkflat_master_path) if self.darkflat_master_path else None,
            "bias_constant": self.bias_constant,
            "groups": [g.to_dict() for g in self.groups],
            "overrides": {
                gid: {k: v.to_dict() for k, v in ov.items()} for gid, ov in self.overrides.items()
            },
            "work_root": str(self.work_root) if self.work_root else None,
            "target_name": self.target_name,
            "settings": self.settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        def frames(key: str) -> list[FrameInfo]:
            return [FrameInfo.from_dict(f) for f in d.get(key, [])]

        def path(key: str) -> Optional[Path]:
            return Path(d[key]) if d.get(key) else None

        p = cls(
            sensor_override=d.get("sensor_override", "auto"),
            session_mode=d.get("session_mode", "auto"),
            lights=frames("lights"),
            dark_pool=frames("dark_pool"),
            flat_pool=frames("flat_pool"),
            bias_pool=frames("bias_pool"),
            darkflat_pool=frames("darkflat_pool"),
            dark_mode=d.get("dark_mode", "frames"),
            flat_mode=d.get("flat_mode", "frames"),
            bias_mode=d.get("bias_mode", "none"),
            darkflat_mode=d.get("darkflat_mode", "none"),
            dark_master_path=path("dark_master_path"),
            flat_master_path=path("flat_master_path"),
            bias_master_path=path("bias_master_path"),
            darkflat_master_path=path("darkflat_master_path"),
            bias_constant=d.get("bias_constant", 2048.0),
            groups=[LightGroup.from_dict(g) for g in d.get("groups", [])],
            overrides={
                gid: {k: MasterSource.from_dict(v) for k, v in ov.items()}
                for gid, ov in d.get("overrides", {}).items()
            },
            work_root=path("work_root"),
            target_name=d.get("target_name", ""),
            settings=Settings.from_dict(d.get("settings")),
        )
        return p

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Project":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def session_label(key: Optional[str]) -> str:
    """セッションキーの表示名。フォルダパスなら末尾のフォルダ名、日付ならそのまま"""
    if not key:
        return ""
    if "/" in key or "\\" in key:
        return Path(key).name or key
    return key


def _sanitize(name: str) -> str:
    """ファイル名に使えない文字と空白を置き換える"""
    bad = '<>:"/\\|?* '
    return "".join("_" if c in bad else c for c in name)
