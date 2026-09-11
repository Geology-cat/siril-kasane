"""
配布用の単一ファイル版 Kasane.py を作る

  python tools/build_single_file.py [--out dist/Kasane.py]

kasane/ パッケージを zip にして base64 で埋め込み、起動時に一時フォルダへ展開して
zipimport で読み込む。ユーザーはこの 1 ファイルを Siril のスクリプトフォルダに置くだけでよい。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kasane import __version__  # noqa: E402

TEMPLATE = '''# -*- coding: utf-8 -*-
"""
Kasane - WBPP 風バッチ前処理 GUI（Siril 1.4 用）  単一ファイル版
Version: {version}
Author: yamashitaujou (Geology-cat)
Homepage: https://github.com/Geology-cat/siril-kasane
License: GPL-3.0-or-later

Light / Dark / Flat / Bias をドラッグ&ドロップして RUN するだけで、
マスター作成 → キャリブレーション → レジストレーション → 品質フィルタ → スタックまでを自動実行します。
DSLR RAW（CR2 など）と CMOS の FITS、OSC / Mono、複数夜のセッションに対応しています。

このファイルは kasane パッケージを埋め込んだ単一ファイル版です（tools/build_single_file.py で生成）。
Siril のスクリプトフォルダ（環境設定 → スクリプト）に置くと Scripts メニューに Kasane が出ます。
ソースコード: https://github.com/Geology-cat/siril-kasane
"""

import base64
import hashlib
import os
import sys
import tempfile

_VERSION = "{version}"
_SHA256 = "{sha256}"
_PAYLOAD = (
{payload}
)


def _extract() -> str:
    """埋め込んだ zip を一時フォルダに書き出し、そのパスを返す（同じ内容なら再利用）"""
    data = base64.b64decode("".join(_PAYLOAD))
    cache = os.path.join(tempfile.gettempdir(), "kasane_" + _SHA256[:16])
    os.makedirs(cache, exist_ok=True)
    zpath = os.path.join(cache, "kasane.zip")
    if not os.path.exists(zpath) or os.path.getsize(zpath) != len(data):
        with open(zpath, "wb") as fh:
            fh.write(data)
    return zpath


def main() -> int:
    zpath = _extract()
    if zpath not in sys.path:
        sys.path.insert(0, zpath)
    from kasane.main import main as _main

    return _main()


if __name__ == "__main__":
    sys.exit(main())
'''


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted((ROOT / "kasane").rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            zf.write(p, str(p.relative_to(ROOT)))
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "Kasane.py")
    args = ap.parse_args()

    data = build_zip()
    b64 = base64.b64encode(data).decode("ascii")
    lines = [f'    "{b64[i:i + 100]}"' for i in range(0, len(b64), 100)]
    text = TEMPLATE.format(version=__version__, sha256=hashlib.sha256(data).hexdigest(), payload="\n".join(lines))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB, zip {len(data) / 1024:.0f} KB, version {__version__})")


if __name__ == "__main__":
    main()
