"""
共通ウィジェット
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QWidget,
)


class DropTreeWidget(QTreeWidget):
    """ファイル / フォルダのドロップを受け付けるツリー。dropped(paths) を発火する"""

    dropped = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class PathPicker(QWidget):
    """パス入力 + 参照ボタン"""

    changed = pyqtSignal(str)

    def __init__(self, mode: str = "dir", filter_text: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode  # "dir" | "file"
        self.filter_text = filter_text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.edit.text()))
        self.button = QPushButton("参照…")
        self.button.clicked.connect(self._browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.button)

    def _browse(self) -> None:
        start = self.edit.text() or str(Path.home())
        if self.mode == "dir":
            path = QFileDialog.getExistingDirectory(self, "フォルダを選択", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "ファイルを選択", start, self.filter_text or "すべて (*)")
        if path:
            self.edit.setText(path)
            self.changed.emit(path)

    def path(self) -> Optional[Path]:
        t = self.edit.text().strip()
        return Path(t) if t else None

    def set_path(self, path: Optional[Path]) -> None:
        self.edit.setText(str(path) if path else "")


class LabeledCombo(QComboBox):
    """(値, 表示名) の辞書から作るコンボ"""

    def __init__(self, options: dict[str, str], parent=None):
        super().__init__(parent)
        self._keys = list(options.keys())
        for k, label in options.items():
            self.addItem(label, k)

    def value(self) -> str:
        return self.currentData()

    def set_value(self, key: str) -> None:
        idx = self.findData(key)
        if idx >= 0:
            self.setCurrentIndex(idx)


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: gray; font-size: 11px;")
    return lbl


def confirm(parent, title: str, text: str) -> bool:
    from PyQt6.QtWidgets import QMessageBox

    r = QMessageBox.question(parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return r == QMessageBox.StandardButton.Yes
