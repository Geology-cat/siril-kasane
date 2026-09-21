"""
Frames タブ: センサー種別、Light（グループツリー）、Dark / Flat / Bias / Dark Flat の投入と割当て表示
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import grouping
from ..grouping import SESSION_MODES, SESSION_MODES_HELP
from ..metadata.reader import collect_files, read_frames
from ..model import FrameInfo, FrameKind, MasterSource, Project
from ..pipeline.offset import describe_offset, resolve_light_offset
from .widgets import DropTreeWidget, LabeledCombo, PathPicker, confirm, hint

FILE_FILTER = ("画像 (*.fit *.fits *.fts *.cr2 *.cr3 *.nef *.arw *.raf *.orf *.rw2 *.pef *.dng "
               "*.jpg *.jpeg *.png *.tif *.tiff *.heic *.avif);;すべて (*)")
COLOR_WARN = QColor(200, 120, 0)
COLOR_ERR = QColor(200, 40, 40)
COLOR_OK = QColor(40, 140, 60)
# 各種別の既定の供給方法（起動時と「すべてクリア」で使う。Project の既定値と揃える）
DEFAULT_MODES = {
    FrameKind.DARK: "frames",
    FrameKind.FLAT: "frames",
    FrameKind.BIAS: "none",
    FrameKind.DARKFLAT: "none",
}


class FrameListPanel(QWidget):
    """1 種別分のリスト（Light 以外）。モード選択 + ファイルリスト + マスター指定"""

    changed = pyqtSignal()

    def __init__(self, kind: FrameKind, modes: dict[str, str], parent=None):
        super().__init__(parent)
        self.kind = kind
        self.frames: list[FrameInfo] = []
        self.modes = modes

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        self.title = QLabel(f"<b>{kind.label}</b>")
        self.count = QLabel("0 枚")
        head.addWidget(self.title)
        head.addWidget(self.count)
        head.addStretch()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        for key, label in modes.items():
            rb = QRadioButton(label)
            if key == "library":
                rb.setToolTip("Library タブのマスターライブラリから、条件の合うマスターを自動で選びます")
            self.mode_group.addButton(rb)
            self.mode_buttons[key] = rb
            head.addWidget(rb)
            rb.toggled.connect(self._mode_toggled)
        lay.addLayout(head)

        body = QHBoxLayout()
        self.tree = DropTreeWidget()
        self.tree.setHeaderLabels(["ファイル", "情報"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setMinimumHeight(70)
        self.tree.setMaximumHeight(140)
        self.tree.dropped.connect(self.add_paths)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        body.addWidget(self.tree, 1)

        btns = QVBoxLayout()
        self.btn_files = QPushButton("＋ファイル")
        self.btn_folder = QPushButton("＋フォルダ")
        self.btn_clear = QPushButton("クリア")
        self.btn_files.clicked.connect(self._add_files)
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_clear.clicked.connect(self.clear)
        for b in (self.btn_files, self.btn_folder, self.btn_clear):
            btns.addWidget(b)
        btns.addStretch()
        body.addLayout(btns)
        lay.addLayout(body)

        # マスターファイル / 固定値
        extra = QHBoxLayout()
        self.master_picker = PathPicker(mode="file", filter_text="FITS (*.fit *.fits *.fts);;すべて (*)",
                                        placeholder="既存のマスター FITS")
        self.master_picker.changed.connect(lambda _: self.changed.emit())
        self.master_label = QLabel("マスター:")
        extra.addWidget(self.master_label)
        extra.addWidget(self.master_picker, 1)
        self.constant_label = QLabel("固定値:")
        self.constant = QDoubleSpinBox()
        self.constant.setRange(0, 65535)
        self.constant.setDecimals(0)
        self.constant.setValue(2048)
        self.constant.valueChanged.connect(lambda _: self.changed.emit())
        extra.addWidget(self.constant_label)
        extra.addWidget(self.constant)
        lay.addLayout(extra)
        self._mode_toggled()

    # ---- モード ----------------------------------------------------------------

    def mode(self) -> str:
        for key, rb in self.mode_buttons.items():
            if rb.isChecked():
                return key
        return "none"

    def set_mode(self, key: str) -> None:
        rb = self.mode_buttons.get(key)
        if rb:
            rb.setChecked(True)

    def _mode_toggled(self) -> None:
        m = self.mode()
        self.tree.setEnabled(m == "frames")
        self.btn_files.setEnabled(m == "frames")
        self.btn_folder.setEnabled(m == "frames")
        self.master_picker.setVisible(m == "master_file")
        self.master_label.setVisible(m == "master_file")
        has_const = "constant" in self.modes
        self.constant_label.setVisible(has_const and m == "constant")
        self.constant.setVisible(has_const and m == "constant")
        self.changed.emit()

    # ---- ファイル ----------------------------------------------------------------

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, f"{self.kind.label} を追加", "", FILE_FILTER)
        if paths:
            self.add_paths([Path(p) for p in paths])

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, f"{self.kind.label} のフォルダを追加")
        if d:
            self.add_paths([Path(d)])

    def add_paths(self, paths: list[Path]) -> None:
        files = collect_files(paths)
        known = {str(f.path) for f in self.frames}
        files = [f for f in files if str(f.resolve()) not in known]
        if not files:
            return
        new = _read_with_progress(self, files, self.kind)
        self.frames.extend(new)
        self.set_mode("frames")
        self.refresh()
        self.changed.emit()

    def add_frames(self, frames: list[FrameInfo]) -> None:
        known = {str(f.path) for f in self.frames}
        self.frames.extend(f for f in frames if str(f.path) not in known)
        if self.frames:
            self.set_mode("frames")
        self.refresh()
        self.changed.emit()

    def clear(self) -> None:
        self.frames.clear()
        self.refresh()
        self.changed.emit()

    def reset(self, mode: str) -> None:
        """フレーム・マスターファイル・固定値・モードを初期状態に戻す（シグナルは出さない）"""
        self.blockSignals(True)
        try:
            self.frames.clear()
            self.master_picker.set_path(None)
            self.constant.setValue(2048)
            self.set_mode(mode)
            self.refresh()
        finally:
            self.blockSignals(False)

    def remove_selected(self) -> None:
        sel = {id(item.data(0, Qt.ItemDataRole.UserRole)) for item in self.tree.selectedItems()}
        self.frames = [f for f in self.frames if id(f) not in sel]
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        self.tree.clear()
        for f in self.frames:
            item = QTreeWidgetItem([f.name, f.summary() + (f"  ⚠ {f.error}" if f.error else "")])
            item.setData(0, Qt.ItemDataRole.UserRole, f)
            item.setToolTip(0, str(f.path))
            if f.error:
                item.setForeground(1, COLOR_WARN)
            self.tree.addTopLevelItem(item)
        self.count.setText(f"{len(self.frames)} 枚")

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_rm = QAction("選択したファイルを削除", self)
        act_rm.triggered.connect(self.remove_selected)
        act_show = QAction("Finder で表示", self)
        act_show.triggered.connect(self._reveal)
        menu.addAction(act_rm)
        menu.addAction(act_show)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _reveal(self) -> None:
        items = self.tree.selectedItems()
        if items:
            f = items[0].data(0, Qt.ItemDataRole.UserRole)
            _reveal_in_finder(f.path)


class FramesTab(QWidget):
    """Frames タブ全体"""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lights: list[FrameInfo] = []
        self._project_for_groups: Optional[Project] = None

        outer = QVBoxLayout(self)

        # センサー + まとめて追加
        top = QHBoxLayout()
        top.addWidget(QLabel("センサー:"))
        self.sensor_group = QButtonGroup(self)
        self.sensor_buttons: dict[str, QRadioButton] = {}
        for key, label in (("auto", "自動判定"), ("osc", "OSC（カラー）"), ("mono", "Mono")):
            rb = QRadioButton(label)
            self.sensor_group.addButton(rb)
            self.sensor_buttons[key] = rb
            top.addWidget(rb)
            rb.toggled.connect(lambda _c: self.changed.emit())
        self.sensor_buttons["auto"].setChecked(True)
        self.sensor_detected = QLabel("")
        top.addWidget(self.sensor_detected)
        top.addSpacing(16)
        top.addWidget(QLabel("セッション:"))
        self.session_mode = LabeledCombo(SESSION_MODES)
        self.session_mode.setToolTip(SESSION_MODES_HELP)
        self.session_mode.currentIndexChanged.connect(lambda _i: self.changed.emit())
        top.addWidget(self.session_mode)
        top.addStretch()
        self.btn_bulk = QPushButton("まとめて追加（FITS の IMAGETYP で自動振り分け）…")
        self.btn_bulk.clicked.connect(self._bulk_add)
        top.addWidget(self.btn_bulk)
        self.btn_clear_all = QPushButton("すべてクリア")
        self.btn_clear_all.setToolTip("Light / Dark / Flat / Bias / Dark Flat の投入とマスター指定、グループの上書き設定、"
                                      "対象名、作業フォルダをすべて初期状態に戻します")
        self.btn_clear_all.clicked.connect(self._clear_all)
        top.addWidget(self.btn_clear_all)
        outer.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Vertical)
        outer.addWidget(splitter, 1)

        # Light
        light_box = QGroupBox("Light")
        ll = QVBoxLayout(light_box)
        head = QHBoxLayout()
        self.light_count = QLabel("0 枚")
        head.addWidget(self.light_count)
        head.addStretch()
        self.btn_l_files = QPushButton("＋ファイル")
        self.btn_l_folder = QPushButton("＋フォルダ")
        self.btn_l_clear = QPushButton("クリア")
        self.btn_l_files.clicked.connect(self._add_light_files)
        self.btn_l_folder.clicked.connect(self._add_light_folder)
        self.btn_l_clear.clicked.connect(self.clear_lights)
        for b in (self.btn_l_files, self.btn_l_folder, self.btn_l_clear):
            head.addWidget(b)
        ll.addLayout(head)
        self.light_tree = DropTreeWidget()
        self.light_tree.setHeaderLabels(["グループ / ファイル", "情報", "Dark", "Flat", "Bias / Dark Flat"])
        hdr = self.light_tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3, 4):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.light_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.light_tree.dropped.connect(self.add_light_paths)
        self.light_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.light_tree.customContextMenuRequested.connect(self._light_context_menu)
        ll.addWidget(self.light_tree)
        ll.addWidget(hint("ファイルやフォルダをここにドロップできます。グループ（露出 / Gain / Filter / Binning / サイズ）ごとに"
                          "別々にスタックされ、各グループに合う Dark / Flat が自動で割り当てられます。右クリックで上書きできます。"))
        splitter.addWidget(light_box)

        # キャリブレーションフレーム
        cal_widget = QWidget()
        cl = QVBoxLayout(cal_widget)
        cl.setContentsMargins(0, 0, 0, 0)
        self.panels: dict[FrameKind, FrameListPanel] = {}
        basic = {"frames": "フレーム", "master_file": "マスター", "library": "ライブラリ", "none": "なし"}
        self.panels[FrameKind.DARK] = FrameListPanel(FrameKind.DARK, dict(basic))
        self.panels[FrameKind.FLAT] = FrameListPanel(FrameKind.FLAT, dict(basic))
        self.panels[FrameKind.BIAS] = FrameListPanel(
            FrameKind.BIAS,
            {"frames": "フレーム", "master_file": "マスター", "library": "ライブラリ", "constant": "固定値",
             "offset_keyword": "64×$OFFSET", "none": "なし"})
        self.panels[FrameKind.DARKFLAT] = FrameListPanel(FrameKind.DARKFLAT, dict(basic))
        for kind, mode in DEFAULT_MODES.items():
            self.panels[kind].set_mode(mode)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        for kind in (FrameKind.DARK, FrameKind.FLAT, FrameKind.BIAS, FrameKind.DARKFLAT):
            box = QGroupBox()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(6, 2, 6, 2)
            bl.addWidget(self.panels[kind])
            il.addWidget(box)
            self.panels[kind].changed.connect(self.changed.emit)
        il.addStretch()
        scroll.setWidget(inner)
        cl.addWidget(scroll)
        splitter.addWidget(cal_widget)
        splitter.setSizes([320, 420])

    # ---- センサー ----------------------------------------------------------------

    def sensor_override(self) -> str:
        for key, rb in self.sensor_buttons.items():
            if rb.isChecked():
                return key
        return "auto"

    # ---- Light ---------------------------------------------------------------------

    def _add_light_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Light を追加", "", FILE_FILTER)
        if paths:
            self.add_light_paths([Path(p) for p in paths])

    def _add_light_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Light のフォルダを追加")
        if d:
            self.add_light_paths([Path(d)])

    def add_light_paths(self, paths: list[Path]) -> None:
        files = collect_files(paths)
        known = {str(f.path) for f in self.lights}
        files = [f for f in files if str(f.resolve()) not in known]
        if not files:
            return
        self.lights.extend(_read_with_progress(self, files, FrameKind.LIGHT))
        self.changed.emit()

    def clear_lights(self) -> None:
        self.lights.clear()
        self.changed.emit()

    clear_all_requested = pyqtSignal()

    def _clear_all(self) -> None:
        total = len(self.lights) + sum(len(p.frames) for p in self.panels.values())
        masters = sum(1 for p in self.panels.values() if p.master_picker.path() is not None)
        what = f"投入済みの {total} 枚" if total else "投入済みのフレーム"
        if masters:
            what += f"、マスターファイルの指定 {masters} 件"
        if not confirm(self, "すべてクリア",
                       f"{what}、グループの上書き設定、対象名、作業フォルダをすべて初期状態に戻します。よろしいですか？"):
            return
        self.clear_all()

    def clear_all(self) -> None:
        """
        全種別のフレームとマスターファイル・固定値・モードを初期状態に戻す（確認なし）。
        上書き設定・対象名・作業フォルダは clear_all_requested でメインウィンドウが戻す
        """
        self.lights.clear()
        for kind, panel in self.panels.items():
            panel.reset(DEFAULT_MODES[kind])
        self.sensor_buttons["auto"].setChecked(True)
        self.clear_all_requested.emit()
        self.changed.emit()

    def _remove_selected_lights(self) -> None:
        sel: set[int] = set()
        for item in self.light_tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, FrameInfo):
                sel.add(id(data))
            elif isinstance(data, str):  # グループ
                for i in range(item.childCount()):
                    sel.add(id(item.child(i).data(0, Qt.ItemDataRole.UserRole)))
        self.lights = [f for f in self.lights if id(f) not in sel]
        self.changed.emit()

    def _bulk_add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "まとめて追加（FITS の IMAGETYP で振り分け）", "", FILE_FILTER)
        if not paths:
            return
        files = collect_files([Path(p) for p in paths])
        frames = _read_with_progress(self, files, FrameKind.LIGHT)
        classified = grouping.classify_by_image_type(frames)
        unknown = [f for f in frames if f.image_type not in ("light", "dark", "flat", "bias", "darkflat")]
        self.lights.extend(classified[FrameKind.LIGHT])
        for kind in (FrameKind.DARK, FrameKind.FLAT, FrameKind.BIAS, FrameKind.DARKFLAT):
            if classified[kind]:
                self.panels[kind].add_frames(classified[kind])
        if unknown:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.information(
                self, "振り分けできないファイル",
                f"{len(unknown)} 件は IMAGETYP から種別を判定できませんでした（RAW など）。\n"
                "Light / Dark / Flat / Bias の各欄に手動で追加してください。\n例: " + unknown[0].name,
            )
        self.changed.emit()

    # ---- グループツリーの更新 ------------------------------------------------------

    def refresh_groups(self, project: Project) -> None:
        """project.groups をツリーに反映する（build_groups 済みであること）"""
        self._project_for_groups = project
        self.light_tree.clear()
        expanded_default = len(project.groups) <= 3
        for g in project.groups:
            top = QTreeWidgetItem([
                f"{g.group_id}  {g.label}",
                f"{len(g.frames)} 枚",
                _ms_text(g.dark, project.settings.calibration.use_dark),
                _ms_text(g.flat, project.settings.calibration.use_flat),
                _bias_text(g, project),
            ])
            top.setData(0, Qt.ItemDataRole.UserRole, g.group_id)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            off = resolve_light_offset(project, g)
            if off.mode == "missing":
                top.setForeground(4, COLOR_ERR)
            elif off.is_auto:
                top.setForeground(4, COLOR_OK)
            note = describe_offset(off)
            if note:
                top.setToolTip(4, note)
            for col, src in ((2, g.dark), (3, g.flat)):
                if src.mode == "none":
                    top.setForeground(col, COLOR_ERR)
                elif src.note:
                    top.setForeground(col, COLOR_WARN)
                else:
                    top.setForeground(col, COLOR_OK)
                top.setToolTip(col, src.note or src.describe())
            for f in g.frames:
                child = QTreeWidgetItem([f.name, f.summary() + (f"  ⚠ {f.error}" if f.error else "")])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                child.setToolTip(0, str(f.path))
                if f.error:
                    child.setForeground(1, COLOR_WARN)
                top.addChild(child)
            self.light_tree.addTopLevelItem(top)
            top.setExpanded(expanded_default)
        n_sessions = len({g.session for g in project.groups if g.session})
        self.light_count.setText(
            f"{len(self.lights)} 枚 / {len(project.groups)} グループ" + (f" / {n_sessions} セッション" if n_sessions else "")
        )
        det = project.detected_sensor()
        self.sensor_detected.setText(
            {"osc": "→ 判定: OSC（カラー）", "mono": "→ 判定: Mono", "rgb": "→ 非線形画像（キャリブレーションなし）",
             "unknown": "→ 判定できません（手動で選択してください）"}[det]
            if self.lights else ""
        )
        # 非線形画像ではキャリブレーションフレームを使わないので入力欄を無効化する
        nonlinear = project.is_nonlinear
        for rb in self.sensor_buttons.values():
            rb.setEnabled(not nonlinear)
        for panel in self.panels.values():
            panel.setEnabled(not nonlinear)
            panel.setToolTip("非線形画像（JPEG / PNG / TIFF）ではキャリブレーションを行いません" if nonlinear else "")

    def _light_context_menu(self, pos) -> None:
        item = self.light_tree.itemAt(pos)
        menu = QMenu(self)
        act_rm = QAction("選択したファイル / グループを削除", self)
        act_rm.triggered.connect(self._remove_selected_lights)
        menu.addAction(act_rm)
        if item is not None:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, FrameInfo):
                act_show = QAction("Finder で表示", self)
                act_show.triggered.connect(lambda: _reveal_in_finder(data.path))
                menu.addAction(act_show)
                gid = item.parent().data(0, Qt.ItemDataRole.UserRole) if item.parent() else None
            else:
                gid = data
            if gid:
                menu.addSeparator()
                for kind, label in ((FrameKind.DARK, "Dark"), (FrameKind.FLAT, "Flat"), (FrameKind.BIAS, "Bias"),
                                    (FrameKind.DARKFLAT, "Dark Flat")):
                    act = QAction(f"このグループの {label} をマスターファイルで指定…", self)
                    act.triggered.connect(lambda _c, k=kind, g=gid: self._override_master(g, k))
                    menu.addAction(act)
                act_reset = QAction("このグループの上書きを解除（自動割当てに戻す）", self)
                act_reset.triggered.connect(lambda _c, g=gid: self._clear_override(g))
                menu.addAction(act_reset)
        menu.exec(self.light_tree.viewport().mapToGlobal(pos))

    overrides_changed = pyqtSignal(str, str, object)  # group_id, kind, MasterSource|None

    def _override_master(self, gid: str, kind: FrameKind) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"{gid} の {kind.label} マスターを選択", "", "FITS (*.fit *.fits *.fts)")
        if path:
            self.overrides_changed.emit(gid, kind.value, MasterSource(mode="master_file", master_path=Path(path), auto=False))

    def _clear_override(self, gid: str) -> None:
        self.overrides_changed.emit(gid, "", None)

    # ---- Project との同期 -----------------------------------------------------------

    def store(self, p: Project) -> None:
        p.sensor_override = self.sensor_override()
        p.session_mode = self.session_mode.value()
        p.lights = list(self.lights)
        for kind, attr in ((FrameKind.DARK, "dark"), (FrameKind.FLAT, "flat"), (FrameKind.BIAS, "bias"),
                           (FrameKind.DARKFLAT, "darkflat")):
            panel = self.panels[kind]
            setattr(p, f"{attr}_pool", list(panel.frames))
            setattr(p, f"{attr}_mode", panel.mode())
            setattr(p, f"{attr}_master_path", panel.master_picker.path())
        p.bias_constant = self.panels[FrameKind.BIAS].constant.value()

    def load(self, p: Project) -> None:
        self.sensor_buttons.get(p.sensor_override, self.sensor_buttons["auto"]).setChecked(True)
        self.session_mode.set_value(p.session_mode)
        self.lights = list(p.lights)
        for kind, attr in ((FrameKind.DARK, "dark"), (FrameKind.FLAT, "flat"), (FrameKind.BIAS, "bias"),
                           (FrameKind.DARKFLAT, "darkflat")):
            panel = self.panels[kind]
            panel.frames = list(getattr(p, f"{attr}_pool"))
            panel.blockSignals(True)
            panel.set_mode(getattr(p, f"{attr}_mode"))
            panel.master_picker.set_path(getattr(p, f"{attr}_master_path"))
            panel.blockSignals(False)
            panel.refresh()
        self.panels[FrameKind.BIAS].constant.setValue(p.bias_constant)

    def set_enabled_all(self, enabled: bool) -> None:
        self.setEnabled(enabled)


# ---- ヘルパー ---------------------------------------------------------------------


def _ms_text(src: MasterSource, used: bool) -> str:
    if not used:
        return "（使わない）"
    if src.mode == "frames":
        return f"{len(src.frames)} 枚" + ("  ⚠" if src.note else "")
    if src.mode == "master_file":
        return f"M: {src.master_path.name if src.master_path else '?'}"
    if src.mode == "none":
        return "なし"
    return src.describe()


def _bias_text(g, project: Project) -> str:
    c = project.settings.calibration
    parts = []
    off = resolve_light_offset(project, g)
    if off.mode == "auto_black":
        parts.append(f"B(自動): 黒レベル {off.black_level:g}")
    elif off.mode == "auto_bias":
        parts.append("B(自動): " + _ms_text(g.bias, True))
    elif off.mode == "missing":
        parts.append("B: なし ⚠ 過補正")
    elif c.flat_calib_mode == "bias" or c.use_bias_for_light:
        parts.append("B: " + _ms_text(g.bias, True))
    if c.flat_calib_mode == "darkflat":
        parts.append("DF: " + _ms_text(g.darkflat, True))
    return "  ".join(parts) or "—"


def _read_with_progress(parent: QWidget, files: list[Path], kind: FrameKind) -> list[FrameInfo]:
    if len(files) < 20:
        return read_frames(files, kind)
    dlg = QProgressDialog(f"{kind.label} のメタデータを読み込み中…", "中止", 0, len(files), parent)
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(300)
    out: list[FrameInfo] = []

    def progress(i: int, n: int) -> None:
        dlg.setValue(i)
        from PyQt6.QtWidgets import QApplication

        QApplication.processEvents()

    for i, f in enumerate(files):
        if dlg.wasCanceled():
            break
        out.extend(read_frames([f], kind))
        progress(i + 1, len(files))
    dlg.setValue(len(files))
    return out


def _reveal_in_finder(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception:
        pass
