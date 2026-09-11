"""
パイプライン実行用の QThread ワーカー

siril.cmd() は必ずこのスレッドから呼ぶ。GUI スレッドでは呼ばない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..headless import run_project
from ..model import Project
from ..pipeline import Cancelled, PipelineError, AnalyzeError
from ..util.log import Level


class PipelineWorker(QThread):
    log = pyqtSignal(str, str)  # text, level
    progress = pyqtSignal(float, str)
    finished_ok = pyqtSignal(str)  # 出力フォルダ
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, project: Project, siril, library_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.project = project
        self.siril = siril
        self.library_dir = library_dir
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def _is_cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:  # noqa: D401
        def sink(text: str, level: Level) -> None:
            self.log.emit(text, level.value)

        def on_progress(value: float, text: str) -> None:
            self.progress.emit(value, text)

        try:
            work = run_project(
                self.project,
                self.siril,
                log_sink=sink,
                is_cancelled=self._is_cancelled,
                on_progress=on_progress,
                library_dir=self.library_dir,
            )
            self.finished_ok.emit(str(work.output))
        except Cancelled:
            self.cancelled.emit()
        except (PipelineError, AnalyzeError) as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
