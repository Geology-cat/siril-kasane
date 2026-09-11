"""
マスターライブラリ

作成したマスター Dark / Flat / Bias / Dark Flat を、メタデータ付きでフォルダに蓄積し、
次回以降は投入フレームが無くても自動でマッチングして使えるようにする。

構造:
  <library>/
    dark_30s_G100_-10C_1x1_480x360_20260911-1530.fit
    dark_30s_G100_-10C_1x1_480x360_20260911-1530.json   ← メタデータ（FrameInfo 相当 + 枚数 + 作成日時）
    flat_Ha_...
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .model import FrameInfo, FrameKind


@dataclass
class LibraryEntry:
    fit_path: Path
    kind: FrameKind
    exposure: Optional[float] = None
    iso_or_gain: Optional[float] = None
    filter: Optional[str] = None
    binning: Optional[int] = None
    temperature: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    sensor: str = "unknown"
    source: str = "fits"
    instrument: Optional[str] = None
    n_frames: int = 0
    created: Optional[datetime] = None
    date_obs: Optional[datetime] = None  # 素材の撮影日
    note: str = ""

    @property
    def json_path(self) -> Path:
        return self.fit_path.with_suffix(".json")

    def as_frame(self) -> FrameInfo:
        """マッチング用に FrameInfo として扱う（path はマスター FITS）"""
        f = FrameInfo(
            path=self.fit_path,
            kind=self.kind,
            source=self.source,
            sensor=self.sensor,
            exposure=self.exposure,
            iso_or_gain=self.iso_or_gain,
            filter=self.filter,
            binning=self.binning,
            temperature=self.temperature,
            width=self.width,
            height=self.height,
            date_obs=self.date_obs,
            instrument=self.instrument,
        )
        try:
            f.file_size = self.fit_path.stat().st_size
        except OSError:
            pass
        return f

    def summary(self) -> str:
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
            parts.append(f"{self.temperature:.0f}℃")
        if self.width and self.height:
            parts.append(f"{self.width}x{self.height}")
        return "  ".join(parts)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "exposure": self.exposure,
            "iso_or_gain": self.iso_or_gain,
            "filter": self.filter,
            "binning": self.binning,
            "temperature": self.temperature,
            "width": self.width,
            "height": self.height,
            "sensor": self.sensor,
            "source": self.source,
            "instrument": self.instrument,
            "n_frames": self.n_frames,
            "created": self.created.isoformat() if self.created else None,
            "date_obs": self.date_obs.isoformat() if self.date_obs else None,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, fit_path: Path, d: dict) -> "LibraryEntry":
        def dt(v):
            return datetime.fromisoformat(v) if v else None

        return cls(
            fit_path=fit_path,
            kind=FrameKind(d.get("kind", "dark")),
            exposure=d.get("exposure"),
            iso_or_gain=d.get("iso_or_gain"),
            filter=d.get("filter"),
            binning=d.get("binning"),
            temperature=d.get("temperature"),
            width=d.get("width"),
            height=d.get("height"),
            sensor=d.get("sensor", "unknown"),
            source=d.get("source", "fits"),
            instrument=d.get("instrument"),
            n_frames=d.get("n_frames", 0),
            created=dt(d.get("created")),
            date_obs=dt(d.get("date_obs")),
            note=d.get("note", ""),
        )


def default_library_dir(config_dir: Path) -> Path:
    return Path(config_dir) / "kasane" / "library"


def resolve_library_dir(settings_path: str, config_dir: Optional[Path]) -> Optional[Path]:
    """設定のパスが空なら既定のライブラリフォルダ。config_dir も無ければ None"""
    if settings_path and settings_path.strip():
        return Path(settings_path.strip()).expanduser()
    if config_dir is not None:
        return default_library_dir(config_dir)
    return None


class MasterLibrary:
    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_dir()

    def entries(self, kind: Optional[FrameKind] = None) -> list[LibraryEntry]:
        if not self.exists():
            return []
        out: list[LibraryEntry] = []
        for js in sorted(self.path.glob("*.json")):
            fit = None
            for ext in (".fit", ".fits", ".fts"):
                cand = js.with_suffix(ext)
                if cand.exists():
                    fit = cand
                    break
            if fit is None:
                continue
            try:
                entry = LibraryEntry.from_json(fit, json.loads(js.read_text(encoding="utf-8")))
            except Exception:
                continue
            if kind is None or entry.kind == kind:
                out.append(entry)
        return out

    def frames(self, kind: FrameKind) -> list[FrameInfo]:
        """grouping のマッチングに渡す FrameInfo のリスト（1 マスター = 1 フレーム扱い）"""
        return [e.as_frame() for e in self.entries(kind)]

    def add(self, kind: FrameKind, master_fit: Path, template: FrameInfo, n_frames: int, note: str = "") -> LibraryEntry:
        """作成済みマスターをライブラリにコピーして登録する"""
        self.path.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        entry = LibraryEntry(
            fit_path=self.path / "placeholder.fit",
            kind=kind,
            exposure=template.exposure,
            iso_or_gain=template.iso_or_gain,
            filter=template.filter,
            binning=template.binning,
            temperature=template.temperature,
            width=template.width,
            height=template.height,
            sensor=template.sensor,
            source=template.source,
            instrument=template.instrument,
            n_frames=n_frames,
            created=now,
            date_obs=template.date_obs,
            note=note,
        )
        name = self._make_name(entry, now)
        dst = self.path / f"{name}{Path(master_fit).suffix.lower() or '.fit'}"
        i = 1
        while dst.exists():
            i += 1
            dst = self.path / f"{name}_{i}{Path(master_fit).suffix.lower() or '.fit'}"
        shutil.copy2(master_fit, dst)
        entry.fit_path = dst
        entry.json_path.write_text(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return entry

    def remove(self, entry: LibraryEntry) -> None:
        for p in (entry.fit_path, entry.json_path):
            try:
                p.unlink()
            except OSError:
                pass

    @staticmethod
    def _make_name(e: LibraryEntry, now: datetime) -> str:
        parts = [e.kind.value]
        if e.filter:
            parts.append(_safe(e.filter))
        if e.exposure is not None:
            parts.append(f"{e.exposure:g}s")
        if e.iso_or_gain is not None:
            parts.append(("ISO" if e.source == "raw" else "G") + f"{e.iso_or_gain:g}")
        if e.temperature is not None:
            parts.append(f"{e.temperature:.0f}C")
        if e.binning:
            parts.append(f"{e.binning}x{e.binning}")
        if e.width and e.height:
            parts.append(f"{e.width}x{e.height}")
        parts.append(now.strftime("%Y%m%d-%H%M"))
        return "_".join(parts)


def _safe(name: str) -> str:
    bad = '<>:"/\\|?* '
    return "".join("_" if c in bad else c for c in name)
