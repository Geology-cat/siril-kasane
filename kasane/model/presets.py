"""
プリセット（設定のみ）と直前プロジェクトの保存・読込

保存先: <Siril 設定ディレクトリ>/kasane/
  presets/<name>.json   設定プリセット
  last_project.json     直前のプロジェクト状態
"""

from __future__ import annotations

import json
from pathlib import Path

from .settings import Settings
from .project import Project

BUILTIN_PRESETS: dict[str, dict] = {
    "DSLR OSC 標準": {
        "calibration": {"dark_opt": "off", "equalize_cfa": True},
        "stacking": {"rgb_equal": True},
        "output": {"mirrorx": "auto"},
    },
    "CMOS OSC 標準": {
        "calibration": {"flat_calib_mode": "darkflat", "dark_opt": "off"},
        "stacking": {"rgb_equal": True},
    },
    "CMOS Mono 標準": {
        "calibration": {"flat_calib_mode": "darkflat", "dark_opt": "off", "equalize_cfa": False},
        "stacking": {"rgb_equal": False},
    },
    "Bayer Drizzle 2x": {
        "drizzle": {"enabled": True, "scale": 2.0, "pixfrac": 0.9, "kernel": "square"},
    },
}


class PresetStore:
    def __init__(self, config_dir: Path):
        self.base = Path(config_dir) / "kasane"
        self.presets_dir = self.base / "presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)

    # ---- プリセット ---------------------------------------------------------

    def list_names(self) -> list[str]:
        user = sorted(p.stem for p in self.presets_dir.glob("*.json"))
        builtin = [n for n in BUILTIN_PRESETS if n not in user]
        return builtin + user

    def is_builtin(self, name: str) -> bool:
        return name in BUILTIN_PRESETS and not (self.presets_dir / f"{name}.json").exists()

    def load(self, name: str) -> Settings:
        path = self.presets_dir / f"{name}.json"
        if path.exists():
            return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if name in BUILTIN_PRESETS:
            return Settings.from_dict(BUILTIN_PRESETS[name])
        raise FileNotFoundError(name)

    def save(self, name: str, settings: Settings) -> Path:
        path = self.presets_dir / f"{_safe(name)}.json"
        path.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def delete(self, name: str) -> None:
        path = self.presets_dir / f"{_safe(name)}.json"
        if path.exists():
            path.unlink()

    # ---- 直前プロジェクト -----------------------------------------------------

    @property
    def last_project_path(self) -> Path:
        return self.base / "last_project.json"

    def save_last_project(self, project: Project) -> None:
        project.save(self.last_project_path)

    def load_last_project(self) -> Project | None:
        if not self.last_project_path.exists():
            return None
        try:
            return Project.load(self.last_project_path)
        except Exception:
            return None


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in name).strip() or "preset"
