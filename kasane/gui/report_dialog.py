"""
品質レポートの表示ダイアログ（output/quality_*.csv を表形式で表示）
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..report import QualityReport, read_csv

COLOR_EXCLUDED = QColor(200, 40, 40)
COLOR_REF = QColor(40, 110, 200)


class ReportDialog(QDialog):
    def __init__(self, output_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("品質レポート")
        self.resize(900, 600)
        lay = QVBoxLayout(self)
        csvs = sorted(Path(output_dir).glob("quality_*.csv"))
        if not csvs:
            lay.addWidget(QLabel(f"レポートがありません: {output_dir}"))
        else:
            tabs = QTabWidget()
            for c in csvs:
                try:
                    rep = read_csv(c)
                except Exception as e:  # noqa: BLE001
                    lay.addWidget(QLabel(f"{c.name}: 読めませんでした ({e})"))
                    continue
                tabs.addTab(self._make_table(rep), rep.title)
            lay.addWidget(tabs, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)

    @staticmethod
    def _make_table(rep: QualityReport) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        summary = QLabel("\n".join(rep.summary_lines()))
        summary.setWordWrap(True)
        lay.addWidget(summary)
        tree = QTreeWidget()
        tree.setHeaderLabels(["#", "ファイル", "採用", "wFWHM", "FWHM", "真円度", "星数", "背景", "参照"])
        tree.setRootIsDecorated(False)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setSortingEnabled(True)
        hdr = tree.header()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for r in rep.rows:
            g = r.reg
            item = _SortableItem([
                str(r.index), r.name, "○" if r.included else "✖ 除外",
                f"{g.wfwhm:.2f}" if g else "", f"{g.fwhm:.2f}" if g else "", f"{g.roundness:.3f}" if g else "",
                str(g.nb_stars) if g else "", f"{g.background:.5f}" if g else "", "★" if r.reference else "",
            ])
            item.setToolTip(1, r.path)
            if not r.included:
                for col in range(9):
                    item.setForeground(col, COLOR_EXCLUDED)
            elif r.reference:
                item.setForeground(8, COLOR_REF)
            tree.addTopLevelItem(item)
        tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        lay.addWidget(tree, 1)
        return page


class _SortableItem(QTreeWidgetItem):
    def __lt__(self, other):  # 数値列は数値として並べ替える
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.text(col), other.text(col)
        try:
            return float(a) < float(b)
        except ValueError:
            return a < b
