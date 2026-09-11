"""
Library タブ: マスターライブラリの場所・保存設定と、登録済みマスターの一覧
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..library import LibraryEntry, MasterLibrary, default_library_dir
from ..model import Settings
from .widgets import PathPicker, confirm, hint

KIND_LABEL = {"dark": "Dark", "flat": "Flat", "bias": "Bias", "darkflat": "Dark Flat"}


class LibraryTab(QWidget):
    def __init__(self, config_dir: Optional[Path], parent=None):
        super().__init__(parent)
        self.config_dir = config_dir
        lay = QVBoxLayout(self)

        box = QGroupBox("マスターライブラリ")
        form = QFormLayout(box)
        self.path = PathPicker(mode="dir", placeholder=str(default_library_dir(config_dir)) if config_dir else "")
        self.path.changed.connect(lambda _: self.refresh())
        self.save_masters = QCheckBox("実行後、作成したマスター（Dark / Flat / Bias / Dark Flat）をライブラリへコピーする")
        self.auto_fallback = QCheckBox("フレームが投入されていない種別は、ライブラリから条件の合うマスターを自動で補う")
        form.addRow("フォルダ（空なら既定）:", self.path)
        form.addRow(self.save_masters)
        form.addRow(self.auto_fallback)
        form.addRow(hint("Frames タブで種別ごとに「ライブラリ」を選ぶと、投入フレームの代わりにライブラリから露出 / Gain / 温度 / Filter / "
                         "Binning / サイズの合うマスターを使います。マスター FITS と同名の .json にメタデータが入ります。"))
        lay.addWidget(box)

        head = QHBoxLayout()
        self.count = QLabel("")
        head.addWidget(self.count)
        head.addStretch()
        btn_refresh = QPushButton("更新")
        btn_refresh.clicked.connect(self.refresh)
        btn_reveal = QPushButton("Finder で表示")
        btn_reveal.clicked.connect(self._reveal)
        btn_delete = QPushButton("選択を削除")
        btn_delete.clicked.connect(self._delete)
        head.addWidget(btn_refresh)
        head.addWidget(btn_reveal)
        head.addWidget(btn_delete)
        lay.addLayout(head)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["種別", "条件", "枚数", "素材の撮影日", "作成日", "ファイル"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        hdr = self.tree.header()
        for i in range(5):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)

    # ---- 設定との同期 ----------------------------------------------------------

    def load(self, s: Settings) -> None:
        self.path.edit.setText(s.library.path)
        self.save_masters.setChecked(s.library.save_masters)
        self.auto_fallback.setChecked(s.library.auto_fallback)
        self.refresh()

    def store(self, s: Settings) -> None:
        s.library.path = self.path.edit.text().strip()
        s.library.save_masters = self.save_masters.isChecked()
        s.library.auto_fallback = self.auto_fallback.isChecked()

    def library_dir(self) -> Optional[Path]:
        t = self.path.edit.text().strip()
        if t:
            return Path(t).expanduser()
        return default_library_dir(self.config_dir) if self.config_dir else None

    # ---- 一覧 --------------------------------------------------------------------

    def refresh(self) -> None:
        self.tree.clear()
        d = self.library_dir()
        entries = MasterLibrary(d).entries() if d else []
        for e in entries:
            item = QTreeWidgetItem([
                KIND_LABEL.get(e.kind.value, e.kind.value),
                e.summary(),
                str(e.n_frames) if e.n_frames else "",
                e.date_obs.strftime("%Y-%m-%d") if e.date_obs else "",
                e.created.strftime("%Y-%m-%d %H:%M") if e.created else "",
                e.fit_path.name,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            item.setToolTip(5, str(e.fit_path))
            self.tree.addTopLevelItem(item)
        self.count.setText(f"{len(entries)} 件" + (f"  ({d})" if d else ""))

    def _selected(self) -> list[LibraryEntry]:
        return [i.data(0, Qt.ItemDataRole.UserRole) for i in self.tree.selectedItems()]

    def _delete(self) -> None:
        sel = self._selected()
        if not sel:
            return
        if not confirm(self, "ライブラリから削除", f"{len(sel)} 件のマスター FITS と .json を削除します。元に戻せません。よろしいですか？"):
            return
        d = self.library_dir()
        lib = MasterLibrary(d) if d else None
        for e in sel:
            if lib:
                lib.remove(e)
        self.refresh()

    def _reveal(self) -> None:
        d = self.library_dir()
        if d is None:
            return
        d.mkdir(parents=True, exist_ok=True)
        from .frames_tab import _reveal_in_finder

        sel = self._selected()
        _reveal_in_finder(sel[0].fit_path if sel else d / ".")
