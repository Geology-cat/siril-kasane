"""
メインウィンドウ

プリセット / 作業フォルダ / タブ / ログ / 進捗 / Analyze / RUN / 中止
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, grouping
from ..model import MasterSource, Project, Settings
from ..model.presets import PresetStore
from ..pipeline import analyze, build_plan, PlanError
from ..staging import WorkDirs, new_work_root
from .frames_tab import FramesTab
from .library_tab import LibraryTab
from .report_dialog import ReportDialog
from .settings_tabs import CalibrationTab, OutputTab, RegistrationTab, StackingTab
from .widgets import PathPicker, confirm
from .worker import PipelineWorker

LOG_COLORS = {
    "info": None,
    "cmd": QColor(70, 110, 200),
    "ok": QColor(40, 140, 60),
    "warn": QColor(200, 120, 0),
    "error": QColor(200, 40, 40),
}


class MainWindow(QMainWindow):
    def __init__(self, siril, dry_run: bool = False):
        super().__init__()
        self.siril = siril
        self.dry_run = dry_run
        self.project = Project()
        self.worker: Optional[PipelineWorker] = None
        self.config_dir = Path(siril.get_siril_configdir())
        self.store = PresetStore(self.config_dir)
        self.last_output_dir: Optional[Path] = None
        self._loading = False  # UI へ読込中は UI → Project の逆同期を止める

        self.setWindowTitle(f"{APP_NAME} {__version__}" + ("  [dry-run]" if dry_run else ""))
        self.resize(1080, 820)
        self._build_ui()
        self._load_initial_project()
        self._refresh_groups()

    # ---- UI 構築 --------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 上段: プリセット + 作業フォルダ
        top = QHBoxLayout()
        top.addWidget(QLabel("プリセット:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(180)
        self._reload_presets()
        top.addWidget(self.preset_combo)
        btn_load = QPushButton("適用")
        btn_load.clicked.connect(self._apply_preset)
        btn_save = QPushButton("保存…")
        btn_save.clicked.connect(self._save_preset)
        btn_del = QPushButton("削除")
        btn_del.clicked.connect(self._delete_preset)
        top.addWidget(btn_load)
        top.addWidget(btn_save)
        top.addWidget(btn_del)
        top.addSpacing(20)
        top.addWidget(QLabel("対象名:"))
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("空なら Light のフォルダ名")
        self.target_edit.setMaximumWidth(180)
        top.addWidget(self.target_edit)
        top.addWidget(QLabel("作業フォルダ:"))
        self.work_picker = PathPicker(mode="dir", placeholder="空なら Light のフォルダ内の output/。この下に Kasane_日時/ が作られます")
        top.addWidget(self.work_picker, 1)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, 1)

        # タブ
        self.tabs = QTabWidget()
        self.frames_tab = FramesTab()
        self.calib_tab = CalibrationTab()
        self.reg_tab = RegistrationTab()
        self.stack_tab = StackingTab()
        self.out_tab = OutputTab()
        self.lib_tab = LibraryTab(self.config_dir)
        self.tabs.addTab(self.frames_tab, "Frames")
        self.tabs.addTab(self.calib_tab, "Calibration")
        self.tabs.addTab(self.reg_tab, "Registration")
        self.tabs.addTab(self.stack_tab, "Stacking")
        self.tabs.addTab(self.out_tab, "Output")
        self.tabs.addTab(self.lib_tab, "Library")
        self.lib_tab.path.changed.connect(lambda _: self._refresh_groups())
        self.lib_tab.auto_fallback.toggled.connect(lambda _: self._refresh_groups())
        splitter.addWidget(self.tabs)
        self.frames_tab.changed.connect(self._on_frames_changed)
        self.frames_tab.overrides_changed.connect(self._on_override)
        self.frames_tab.clear_all_requested.connect(self._on_clear_all)
        # 設定変更でグループ表示（Bias/DF 列）が変わるので同期する
        for w in (self.calib_tab.flat_mode, self.calib_tab.use_dark, self.calib_tab.use_flat, self.calib_tab.use_bias_light,
                  self.calib_tab.auto_bias):
            sig = getattr(w, "currentIndexChanged", None) or getattr(w, "toggled", None)
            if sig is not None:
                sig.connect(lambda *_: self._refresh_groups())

        # ログ
        log_widget = QWidget()
        ll = QVBoxLayout(log_widget)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("ログ"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)
        self.log_view.setFont(mono)
        ll.addWidget(self.log_view)
        splitter.addWidget(log_widget)
        splitter.setSizes([560, 200])

        # 下段: 進捗 + ボタン
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress_label = QLabel("")
        bottom.addWidget(self.progress, 2)
        bottom.addWidget(self.progress_label, 3)
        self.btn_report = QPushButton("レポート…")
        self.btn_report.setEnabled(False)
        self.btn_report.clicked.connect(self._show_report)
        bottom.addWidget(self.btn_report)
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.clicked.connect(self._analyze)
        self.btn_run = QPushButton("RUN")
        self.btn_run.setDefault(True)
        self.btn_run.setStyleSheet("font-weight: bold; padding: 4px 18px;")
        self.btn_run.clicked.connect(self._run)
        self.btn_cancel = QPushButton("中止")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        bottom.addWidget(self.btn_analyze)
        bottom.addWidget(self.btn_run)
        bottom.addWidget(self.btn_cancel)
        root.addLayout(bottom)

        self.log(f"{APP_NAME} {__version__} を起動しました", "ok")
        if self.dry_run:
            self.log("dry-run モード: Siril には接続していません。コマンドはログに表示するだけです", "warn")

    # ---- プロジェクト ------------------------------------------------------------------

    def _load_initial_project(self) -> None:
        last = self.store.load_last_project()
        if last is not None:
            self.project = last
            self.log("前回のプロジェクトを復元しました", "info")
        else:
            self.project = Project()
            # 既定プリセットはセンサー種別が決まってから選ぶので、まずは Settings() のまま
        # 作業フォルダが未指定なら Light のフォルダ内の output/ を使う（Project.effective_work_root）
        self._load_project_to_ui()

    def _load_project_to_ui(self) -> None:
        p = self.project
        self._loading = True
        try:
            self.frames_tab.load(p)
            for tab in (self.calib_tab, self.reg_tab, self.stack_tab, self.out_tab, self.lib_tab):
                tab.load(p.settings)
            self.work_picker.set_path(p.work_root)
            self.target_edit.setText(p.target_name)
        finally:
            self._loading = False

    def _store_ui_to_project(self) -> Project:
        p = self.project
        self.frames_tab.store(p)
        for tab in (self.calib_tab, self.reg_tab, self.stack_tab, self.out_tab, self.lib_tab):
            tab.store(p.settings)
        p.work_root = self.work_picker.path()
        p.target_name = self.target_edit.text().strip()
        return p

    def _library_dir(self) -> Optional[Path]:
        return self.lib_tab.library_dir()

    def _refresh_groups(self) -> None:
        if self._loading:
            return
        p = self._store_ui_to_project()
        grouping.build_groups(p, self._library_dir())
        self.frames_tab.refresh_groups(p)

    def _on_frames_changed(self) -> None:
        self._refresh_groups()

    def _on_clear_all(self) -> None:
        """「すべてクリア」: フレームに加え、上書き設定・対象名・作業フォルダも初期状態に戻す"""
        self.project.overrides.clear()
        self.project.target_name = ""
        self.project.work_root = None
        self._loading = True
        try:
            self.target_edit.clear()
            self.work_picker.set_path(None)
        finally:
            self._loading = False
        # frames_tab の changed シグナルの発火順に依存しないよう、ここでもグループ表示を更新する
        self._refresh_groups()
        self.log("すべてクリアしました（フレーム、マスター指定、上書き設定、対象名、作業フォルダ）", "info")

    def _on_override(self, gid: str, kind: str, source) -> None:
        if source is None:
            self.project.overrides.pop(gid, None)
        else:
            self.project.overrides.setdefault(gid, {})[kind] = source
        self._refresh_groups()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            if not confirm(self, "終了", "処理が実行中です。ウィンドウを閉じても Siril 側の処理は続きます。閉じますか？"):
                event.ignore()
                return
        try:
            self.store.save_last_project(self._store_ui_to_project())
        except Exception:
            pass
        event.accept()

    # ---- プリセット --------------------------------------------------------------------

    def _reload_presets(self) -> None:
        cur = self.preset_combo.currentText()
        self.preset_combo.clear()
        self.preset_combo.addItems(self.store.list_names())
        if cur:
            idx = self.preset_combo.findText(cur)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

    def _apply_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            settings = self.store.load(name)
        except Exception as e:
            QMessageBox.warning(self, "プリセット", f"読み込めませんでした: {e}")
            return
        self.project.settings = settings
        self._loading = True
        try:
            for tab in (self.calib_tab, self.reg_tab, self.stack_tab, self.out_tab, self.lib_tab):
                tab.load(settings)
        finally:
            self._loading = False
        self._refresh_groups()
        self.log(f"プリセット「{name}」を適用しました", "info")

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "プリセットを保存", "名前:", text=self.preset_combo.currentText())
        if not ok or not name.strip():
            return
        p = self._store_ui_to_project()
        self.store.save(name.strip(), p.settings)
        self._reload_presets()
        self.preset_combo.setCurrentText(name.strip())
        self.log(f"プリセット「{name.strip()}」を保存しました", "ok")

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not name or self.store.is_builtin(name):
            QMessageBox.information(self, "プリセット", "組み込みプリセットは削除できません")
            return
        if confirm(self, "プリセットを削除", f"「{name}」を削除しますか？"):
            self.store.delete(name)
            self._reload_presets()

    # ---- ログ / 進捗 ---------------------------------------------------------------------

    def log(self, text: str, level: str = "info") -> None:
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        color = LOG_COLORS.get(level)
        if color is not None:
            fmt.setForeground(color)
        if level in ("error", "ok"):
            fmt.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(text + "\n", fmt)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _set_progress(self, value: float, text: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, value)) * 1000))
        self.progress_label.setText(text)

    # ---- Analyze / RUN / 中止 ------------------------------------------------------------

    def _analyze(self, quiet: bool = False) -> list:
        p = self._store_ui_to_project()
        grouping.build_groups(p, self._library_dir())
        self.frames_tab.refresh_groups(p)
        base = p.effective_work_root()
        work_root = new_work_root(base) if base else None
        issues = analyze(p, work_root)
        if not quiet:
            self.log("---- Analyze ----", "info")
        for i in issues:
            self.log(f"{i.icon} {i.text}", {"error": "error", "warn": "warn", "info": "info"}[i.level])
        # コマンド列のプレビュー
        if not any(i.level == "error" for i in issues):
            try:
                plan = build_plan(p, WorkDirs(work_root or Path("/tmp/Kasane")), self._library_dir())
                n_cmd = sum(1 for s in plan.steps if s.kind == "cmd")
                self.log(f"実行予定: {n_cmd} コマンド、出力 {len(plan.outputs)} 件: "
                         + ", ".join(o.name for o in plan.outputs), "info")
                for line in plan.summary:
                    self.log(f"⚠ {line}", "warn")
            except PlanError as e:
                self.log(f"✖ {e}", "error")
                issues.append(type(issues[0])("error", str(e)) if issues else None)
        return [i for i in issues if i is not None]

    def _run(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        issues = self._analyze(quiet=True)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            QMessageBox.critical(self, "実行できません", "\n".join(i.text for i in errors))
            return
        warns = [i for i in issues if i.level == "warn"]
        if warns:
            text = "以下の警告があります。続行しますか？\n\n" + "\n".join(f"・{i.text}" for i in warns[:12])
            if len(warns) > 12:
                text += f"\n…ほか {len(warns) - 12} 件"
            if not confirm(self, "警告", text):
                return
        p = self._store_ui_to_project()
        try:
            self.store.save_last_project(p)
        except Exception:
            pass
        self._set_busy(True)
        self.log("==== 実行開始 ====", "ok")
        self.worker = PipelineWorker(p, self.siril, self._library_dir(), self)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self._set_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_cancel()
            self.btn_cancel.setEnabled(False)
            self.progress_label.setText("現在のコマンドが終わり次第、中止します…（Siril 側の Stop ボタンで即時中断も可）")
            self.log("中止を要求しました。実行中のコマンドが終わり次第停止します", "warn")

    def _set_busy(self, busy: bool) -> None:
        self.tabs.setEnabled(not busy)
        self.btn_run.setEnabled(not busy)
        self.btn_analyze.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.work_picker.setEnabled(not busy)
        self.target_edit.setEnabled(not busy)
        self.preset_combo.setEnabled(not busy)
        if not busy:
            self.worker = None

    def _on_finished(self, output_dir: str) -> None:
        self._set_busy(False)
        self._set_progress(1.0, "完了")
        self.last_output_dir = Path(output_dir)
        self.btn_report.setEnabled(True)
        self.lib_tab.refresh()
        self.log(f"出力フォルダ: {output_dir}", "ok")
        QMessageBox.information(self, "完了", f"前処理が完了しました。\n\n{output_dir}\n\n「レポート…」で品質レポートを確認できます。")

    def _show_report(self) -> None:
        if self.last_output_dir is None:
            return
        ReportDialog(self.last_output_dir, self).exec()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.progress_label.setText("エラーで停止")
        self.log(f"エラー: {message}", "error")
        QMessageBox.critical(self, "エラー", message + "\n\n作業フォルダの log.txt と commands.ssf を確認してください。")

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self.progress_label.setText("中止しました")
        self.log("中止しました。作業フォルダは残っています", "warn")
