# Kasane

Siril 1.4 用の WBPP（PixInsight の Weighted Batch Preprocessing）風バッチ前処理 GUI スクリプトです。
Light / Dark / Flat / Bias をドラッグ&ドロップして RUN するだけで、

**マスター作成 → キャリブレーション → 2-pass レジストレーション → 品質フィルタ → スタック**

までを Siril 本体に実行させます。フォルダを `lights/ darks/ flats/` に整理する必要はありません。

- DSLR RAW（CR2 など）と冷却 CMOS の FITS の両方に対応
- OSC（カラー）と Mono（フィルター別に自動でグループ化してスタック）の両方に対応
- 露出 / ISO・Gain / Filter / Binning / 画像サイズで Light を自動グループ化し、各グループに合う Dark / Flat / Bias を自動割当て
- 複数夜のセッションに対応（フォルダまたは撮影日で自動判定）。セッションごとにその夜の Flat / Dark でキャリブレーションし、同じ条件の Light は結合して 1 本にスタック
- 既存マスター FITS の再利用、Bias の固定値 / `$OFFSET` 指定、Dark Flat
- Bayer Drizzle、wFWHM / 真円度 / 星数などによる不良フレーム除外
- 元画像は移動もコピーもしません（作業フォルダに symlink を張ります）
- 実行後の品質レポート（フレームごとの wFWHM / FWHM / 真円度 / 星数 / 背景と採否、参照フレーム）を CSV と GUI の表で確認
- マスターライブラリ: 作成した Dark / Flat / Bias / Dark Flat をメタデータ付きで蓄積し、次回はフレームを投入しなくても露出 / Gain / 温度 / Filter / サイズの合うマスターを自動で使用
- 非線形画像モード: JPEG / PNG / TIFF などの現像済み・ストレッチ済み画像を、キャリブレーション無しで位置合わせ → スタック
- 「位置合わせしない」モードと Pixel maximum スタックで、固定三脚のタイムラプスから星の軌跡を合成
- 出力は FITS / 16bit TIFF / 両方から選択
- プリセット保存、前回状態の自動復元、実行コマンド列の `.ssf` 書き出し

## 動作環境

- Siril 1.4.0 以降（1.4.4 で開発・検証）
- macOS で検証済み。Windows / Linux は未検証ですが OS 依存の処理は避けています（symlink が使えない環境ではコピーにフォールバックします）
- 依存パッケージ（PyQt6, exifread）は初回起動時に Siril の Python 環境へ自動導入されます

## インストール

### 単一ファイル版（推奨）

1. [Releases](https://github.com/Geology-cat/siril-kasane/releases/latest) から `Kasane.py` をダウンロード
2. Siril のスクリプトフォルダに置く
   - macOS: `~/Library/Application Support/org.siril.Siril/scripts`
   - Windows: `%LOCALAPPDATA%\siril\scripts`
   - Linux: `~/.config/siril/scripts`
   - フォルダが無ければ作成し、Siril の **環境設定 → スクリプト** で「スクリプトの保存場所」に追加してください
3. Siril を再起動（またはスクリプトメニューを更新）すると **Scripts → Kasane** に表示されます

初回起動時に PyQt6 と exifread が Siril の Python 環境へ自動導入されます（数十秒かかります）。

### ソースから（開発者向け）

```bash
git clone https://github.com/Geology-cat/siril-kasane.git
cd siril-kasane
bash tools/install.sh
```

Siril のスクリプトフォルダに `Kasane.py` と `kasane/` の symlink を作ります（macOS 用。他 OS は `SIRIL_SCRIPTS_DIR` を指定）。
手動で置く場合は、`Kasane.py` と `kasane/` フォルダを同じ場所にコピーしてください。
単一ファイル版は `python3 tools/build_single_file.py` で `dist/Kasane.py` に生成できます。

## 使い方

1. Siril で **Scripts → Kasane** を実行
2. **Frames** タブに Light / Dark / Flat（必要なら Bias / Dark Flat）をドロップ
   - FITS なら「まとめて追加」で `IMAGETYP` から自動振り分けもできます
   - Light はグループごとにツリー表示され、割り当てられた Dark / Flat が右側に出ます（右クリックで上書き可）
   - 複数夜のデータは `2026-09-10/lights/`, `2026-09-11/lights/` のようにフォルダが分かれていれば自動でセッション分けされます（「セッション」で切替可）
3. 必要なら **Calibration / Registration / Stacking / Output** タブを調整（プリセットもあります）
4. 作業フォルダを指定して **Analyze** で警告を確認 → **RUN**

結果は `作業フォルダ/Kasane_日時/output/` に `result_<対象名>[_<フィルター>]_<積算秒>s.fit` として保存されます。
同じフォルダの `output/quality_<名前>.csv` に品質レポート、`commands.ssf` に実行したコマンド列、`log.txt` にログ、`project.json` に入力と設定が残ります。
完了後は「レポート…」ボタンで、除外されたフレームと参照フレームを表で確認できます。

## マスターライブラリ

**Library** タブで「実行後、作成したマスターをライブラリへコピーする」を ON にすると、Dark / Flat / Bias / Dark Flat のマスターが
ライブラリフォルダ（既定は Siril 設定フォルダ内の `kasane/library`）にメタデータ付きで保存されます。
次回以降は Frames タブで種別を「ライブラリ」にするか、フレームを投入しないままにすると、条件（露出 / Gain / 温度 / Filter / Binning / サイズ）の合う
マスターが自動で選ばれます。

## 非線形画像（JPEG / PNG / TIFF）のスタック

Light に JPEG / PNG / TIFF / HEIF / AVIF を投入すると自動で **非線形画像モード** になります。

- Dark / Flat / Bias は使いません（入力欄がグレーアウトします）。Drizzle も使えません
- 位置合わせは星による Global Star Alignment が使えます。ストレッチ済みの星像は飽和していて FWHM が計測できないことがあるため、wFWHM / 真円度 / FWHM / 品質フィルタは自動で無効になります（星数 / 背景フィルタは使えます）
- 固定三脚のタイムラプスから星の軌跡を作るには、Registration タブで「位置合わせしない」、Stacking タブで「Pixel maximum stacking」を選びます
- Output タブの「保存形式」で 16bit TIFF を選べます（非線形画像では TIFF が扱いやすいです）
- EXIF の無い書き出し画像は露出が分からないため、結果のファイル名は積算秒ではなく枚数（`_8frames`）になります
- 8bit JPEG は階調が 256 段階しかなく圧縮ノイズもあるので、可能なら 16bit TIFF を入力にしてください

## 作業フォルダの構造

```
Kasane_20260911_213000/
├── project.json     入力ファイル一覧と設定（再現用）
├── commands.ssf     実行した Siril コマンド列
├── log.txt
├── input/           元画像への symlink（種別 / グループごと）
├── process/         変換・中間シーケンス（既定で完了後に削除）
├── masters/         作成したマスター（dark_01.fit, flat_01.fit …）
└── output/          結果
```

## ヘッドレス実行

GUI で保存された `project.json` をそのまま実行できます。

```
pyscript /path/to/Kasane.py --project /path/to/project.json
```

## 開発

```bash
python3 -m venv .venv && .venv/bin/pip install numpy exifread PyQt6
.venv/bin/python -m unittest discover -s tests -t .          # ユニットテスト（Siril 不要）
.venv/bin/python tools/make_test_data.py test_work/data_osc  # 合成テストデータ
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/gui_smoke.py test_work/data_osc test_work/shots  # GUI スモーク
python3 Kasane.py --dry-run                                # Siril なしで GUI を試す
```

Siril 本体での統合テストは `tools/make_test_project.py` で作った JSON を `siril-cli -s` から `pyscript` で実行します（詳細は `PLAN.md`）。

## 不具合報告

[Issues](https://github.com/Geology-cat/siril-kasane/issues) へ。作業フォルダの `log.txt` と `commands.ssf` を添えていただけると助かります。

## ライセンス

GPL-3.0-or-later
