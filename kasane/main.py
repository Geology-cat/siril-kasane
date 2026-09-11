"""
エントリポイント

  Scripts メニューから        : GUI を起動
  pyscript Kasane.py --project p.json : ヘッドレス実行
  python Kasane.py --dry-run          : Siril に接続せず GUI を試す（開発用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__

REQUIRED_PACKAGES = ["PyQt6", "exifread"]


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="Kasane", add_help=False)
    ap.add_argument("--project", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-install", action="store_true", help="ensure_installed を呼ばない（開発用）")
    ns, _unknown = ap.parse_known_args(argv)
    return ns


def _connect_siril(dry_run: bool):
    if dry_run:
        from .pipeline.runner import DryRunSiril

        return DryRunSiril(log=lambda s: print(s, flush=True), delay=0.05)
    import sirilpy as s  # type: ignore

    siril = s.SirilInterface()
    siril.connect()
    return siril


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ns = _parse(argv)

    siril = _connect_siril(ns.dry_run)

    # ヘッドレス
    if ns.project is not None:
        from .headless import main_headless

        return main_headless(ns.project, siril)

    # GUI: 依存パッケージを Siril の venv に導入してから import する
    if not ns.dry_run and not ns.no_install:
        import sirilpy as s  # type: ignore

        try:
            siril.log(f"{APP_NAME} {__version__}: 依存パッケージを確認しています…")
        except Exception:
            pass
        s.ensure_installed(*REQUIRED_PACKAGES)

    from PyQt6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow(siril=siril, dry_run=ns.dry_run)
    win.show()
    return app.exec()
