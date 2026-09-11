#!/bin/bash
# Siril のユーザースクリプトフォルダにランチャーとパッケージを symlink で配置する（開発用）
# 実体はこのリポジトリのまま。Siril → Scripts メニューに「Kasane」が出る。
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="${SIRIL_SCRIPTS_DIR:-$HOME/Library/Application Support/org.siril.Siril/scripts}"
mkdir -p "$SCRIPTS_DIR"
ln -sfn "$HERE/Kasane.py" "$SCRIPTS_DIR/Kasane.py"
ln -sfn "$HERE/kasane" "$SCRIPTS_DIR/kasane"
echo "installed:"
ls -la "$SCRIPTS_DIR"
echo
echo "Siril を再起動（またはスクリプトメニューを更新）すると Scripts → Kasane が表示されます。"
