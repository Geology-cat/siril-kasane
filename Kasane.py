# -*- coding: utf-8 -*-
"""
Kasane - WBPP 風バッチ前処理 GUI（Siril 1.4 用）
Version: 1.1.0
Author: yamashitaujou (Geology-cat)
Homepage: https://github.com/Geology-cat/siril-kasane
License: GPL-3.0-or-later

Light / Dark / Flat / Bias をドラッグ&ドロップして RUN するだけで、
マスター作成 → キャリブレーション → レジストレーション → 品質フィルタ → スタックまでを自動実行します。
DSLR RAW（CR2 など）と CMOS の FITS、OSC / Mono の両方に対応しています。

このファイルはランチャーです。本体は同じフォルダの kasane/ パッケージにあります。
Siril の Scripts メニューから起動するには、このファイルと kasane/ フォルダを
Siril のスクリプトフォルダ（環境設定 → スクリプト）に置いてください。
1 ファイルで済ませたい場合は、GitHub の Releases から単一ファイル版の Kasane.py を使ってください。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from kasane.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
