"""
GUI のスモークテスト（dry-run、オフスクリーン）

  QT_QPA_PLATFORM=offscreen .venv/bin/python tools/gui_smoke.py <data_dir>[,<data_dir2>...] <shot_dir>

MainWindow を DryRunSiril で起動し、テストデータを投入 → Analyze → RUN（dry-run）まで自動操作し、
各タブのスクリーンショットを保存する。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from kasane.gui import main_window  # noqa: E402
from kasane.pipeline.runner import DryRunSiril  # noqa: E402


def main() -> int:
    data_dirs = [Path(d).resolve() for d in sys.argv[1].split(",")]
    shots = Path(sys.argv[2]).resolve()
    shots.mkdir(parents=True, exist_ok=True)

    # 確認ダイアログとメッセージボックスを自動で閉じる
    main_window.confirm = lambda *a, **k: True
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.critical = staticmethod(lambda *a, **k: print("CRITICAL:", a[2]))
    QMessageBox.warning = staticmethod(lambda *a, **k: print("WARNING:", a[2]))

    app = QApplication(sys.argv)
    siril = DryRunSiril(log=lambda s: None, delay=0.01)
    win = main_window.MainWindow(siril=siril, dry_run=True)
    win.show()
    app.processEvents()

    def shot(name: str) -> None:
        app.processEvents()
        win.grab().save(str(shots / f"{name}.png"))

    # 既存の復元プロジェクトをクリアして投入
    win.frames_tab.clear_lights()
    for panel in win.frames_tab.panels.values():
        panel.clear()
    from kasane.model import FrameKind

    for data in data_dirs:
        win.frames_tab.add_light_paths([data / "lights"])
        win.frames_tab.panels[FrameKind.DARK].add_paths([data / "darks"])
        win.frames_tab.panels[FrameKind.FLAT].add_paths([data / "flats"])
        win.frames_tab.panels[FrameKind.DARKFLAT].add_paths([data / "darkflats"])
    win.calib_tab.flat_mode.set_value("darkflat")
    win.work_picker.set_path(Path(sys.argv[2]).resolve() / "work")
    (Path(sys.argv[2]).resolve() / "work").mkdir(exist_ok=True)
    win.target_edit.setText("SmokeTest")
    win._refresh_groups()
    shot("01_frames")

    for i, name in enumerate(("02_calibration", "03_registration", "04_stacking", "05_output", "05b_library"), start=1):
        win.tabs.setCurrentIndex(i)
        shot(name)
    win.tabs.setCurrentIndex(0)

    issues = win._analyze()
    shot("06_analyze")
    print("issues:", [(i.level, i.text) for i in issues])

    win._run()
    t0 = time.time()
    while win.worker is not None and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.02)
    shot("07_after_run")
    if win.last_output_dir is not None:
        from kasane.gui.report_dialog import ReportDialog

        dlg = ReportDialog(win.last_output_dir, win)
        dlg.show()
        app.processEvents()
        dlg.grab().save(str(shots / "08_report.png"))
        dlg.close()
    print("dry-run commands:", len(siril.commands))
    for c in siril.commands[:6]:
        print("  ", " ".join(c))
    print("   ...")
    for c in siril.commands[-4:]:
        print("  ", " ".join(c))
    print("groups:", [(g.group_id, g.label, len(g.frames)) for g in win.project.groups])
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
