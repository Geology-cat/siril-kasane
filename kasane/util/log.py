"""
ログの二重出力（GUI / Siril ログ / ファイル）
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class Level(str, Enum):
    INFO = "info"
    CMD = "cmd"
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


class Logger:
    """
    sink: GUI 側のコールバック (text, level)
    siril: sirilpy.SirilInterface（None 可）
    file: 追記先のファイル（None 可）
    """

    def __init__(
        self,
        sink: Optional[Callable[[str, Level], None]] = None,
        siril=None,
        file: Optional[Path] = None,
    ):
        self.sink = sink
        self.siril = siril
        self.file = file
        self._fh = None
        if file is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(file, "a", encoding="utf-8")

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def log(self, text: str, level: Level = Level.INFO) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {text}"
        if self.sink:
            try:
                self.sink(line, level)
            except Exception:
                pass
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()
        if self.siril is not None:
            try:
                from sirilpy import LogColor  # type: ignore

                color = {
                    Level.INFO: LogColor.DEFAULT,
                    Level.CMD: LogColor.BLUE,
                    Level.OK: LogColor.GREEN,
                    Level.WARN: LogColor.SALMON,
                    Level.ERROR: LogColor.RED,
                }[level]
                # Siril ログは 1022 バイト上限
                self.siril.log(_truncate(f"[Kasane] {text}", 1000), color)
            except Exception:
                pass

    def info(self, text: str) -> None:
        self.log(text, Level.INFO)

    def cmd(self, text: str) -> None:
        self.log(text, Level.CMD)

    def ok(self, text: str) -> None:
        self.log(text, Level.OK)

    def warn(self, text: str) -> None:
        self.log(text, Level.WARN)

    def error(self, text: str) -> None:
        self.log(text, Level.ERROR)


def _truncate(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + "…"
