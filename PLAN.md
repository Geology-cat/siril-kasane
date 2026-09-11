# Kasane 風 GUI スクリプト 作成計画・実装計画

作成日: 2026-09-11
対象: Siril 1.4.4 (macOS) / sirilpy 1.0.25 / Python 3.12（Siril 同梱）

---

## 1. コンセプト

PixInsight の WBPP（Weighted Batch Preprocessing）のように、
**Light / Dark / Flat / Bias を GUI に放り込んで RUN するだけで前処理が完了する** Siril 用 Python スクリプトを作る。

現状の面倒:

```
フォルダを作る → lights/darks/flats/biases に画像を移動 → Siril で親フォルダを指定 → スクリプト起動
```

目標:

```
Siril → Scripts → Kasane → 4 種類をドラッグ&ドロップ → RUN
```

- 元画像は **移動もコピーもしない**（symlink で作業ディレクトリに集約）
- 撮影セッション・露出・ISO/Gain・フィルターによる **自動グループ分け**
- Registration 時の品質評価（wFWHM / roundness / 星数）で **不良フレームを自動除外**
- Drizzle 対応
- 設定はプリセットとして保存・再利用

対象カメラ（最初から両方対応する）:

| 種別 | 入力形式 | センサー | 代表機材 |
|---|---|---|---|
| DSLR | CR2 / CR3 / NEF / ARW など RAW | OSC（CFA） | EOS 6D + FSQ-85EDP |
| 冷却 CMOS | FITS（撮影ソフト出力） | OSC（CFA）または Mono | ASI2600MC Pro / ASI2600MM Pro など |

DSLR と CMOS の違いは **メタデータの取り方（EXIF か FITS ヘッダか）** と **センサー種別（CFA か Mono か）** に集約されるので、
この 2 点を抽象化してパイプラインは共通にする。Mono はフィルター別にグループ化して 1 本ずつスタックする。

---

## 2. ChatGPT ログの評価

### 採用するもの

| 項目 | 理由 |
|---|---|
| Siril 1.4 の `sirilpy` + PyQt6 で GUI スクリプトとして実装 | 公式推奨。Tkinter は 1.6 で廃止予定と明記されている |
| Scripts メニューから起動できる `.py` として作る | 別アプリではなく Siril の中で完結する |
| 4 種類のフレームを GUI で個別投入し、裏で作業ディレクトリを自動生成 | 「フォルダ整理が面倒」という要望への直接の答え |
| symlink で元画像を参照する（コピーしない） | Siril の `convert` は symlink を辿れる。Naztronomy 公式スクリプトも同じ方式（失敗時コピーにフォールバック） |
| 露出 / Gain / Filter / Bin による自動グループ化、複数夜セッション対応 | WBPP との差が一番大きい部分。Siril 標準スクリプトには無い |
| wFWHM / roundness / 星数による自動除外、Drizzle、プリセット保存、ログ表示、中止ボタン | 全て Siril 1.4 の既存機能で実現できることを確認済み |
| 段階的に機能を増やす計画 | 妥当。ただし対象カメラは最初から DSLR + CMOS 両対応にする（下記） |

### 改善・修正するもの

| ログの記述 | 問題 | 改善 |
|---|---|---|
| 「200 枚の CR2 があっても二重に数十 GB 消費する必要はない」 | symlink で節約できるのは **入力ステージングだけ**。CR2 は `convert` で FITS に変換されるので、変換後 FITS + pp_ + r_ の中間ファイルは必ず生成される（元データの 3 倍前後） | 中間ファイル自動削除オプションを付ける。ディスク使用量の見積もりを Analyze 時に表示する |
| 概念コード `calibrate light -cc=dark -cfa -debayer` と `register -2pass` → `stack r_pp_light` | `register -2pass` は変換画像を出力しない。`seqapplyreg` を挟まないと `r_pp_light` は存在しない | 正しい流れ: `register -2pass` → `seqapplyreg -filter-*` → `stack` |
| Drizzle の説明が曖昧 | Siril の Drizzle は **デベイヤー前の CFA 画像**が必須。`calibrate -debayer` と両立しない | Drizzle ON/OFF で `-debayer` の付与を切り替える（公式 `OSC_Preprocessing_BayerDrizzle.ssf` と同じ） |
| 「FITS ヘッダを解析して自動グループ化」 | CR2 には FITS ヘッダが無い | CR2 は EXIF（`exifread`）から露出 / ISO を読む。FITS は `astropy`。両方読めない場合は Siril 変換後に `seqheader` で補完 |
| GUI モックが単一画面で、設定項目が平坦 | 設定が増えると破綻する | タブ構成（Frames / Calibration / Registration / Stacking / Output）+ 常時表示のログ + RUN |
| スレッドの話が無い | Naztronomy スクリプトは `siril.cmd()` をメインスレッドで呼ぶため、処理中に GUI が固まる | QThread ワーカー + シグナルで進捗・ログを GUI に流す。公式ドキュメントも「長時間コマンドは別スレッド」を推奨 |
| Sirilic の紹介 | 今回の目的（自作 GUI）とは無関係 | 不採用 |
| Bias の扱いが未検討 | EOS 6D で Bias を毎回撮るのは現実的でない | Bias は「フレーム / 既存マスター / 固定値 / なし」から選べるようにする（`-bias="=2048"` 形式を Siril がサポート） |
| マスターフレームの再利用が無い | WBPP の重要機能。Dark ライブラリを使い回したい | 各種別に「フレームから作る」か「既存マスター FITS を指定」かを選べるようにする |
| 「最初は EOS 6D / OSC に絞る」 | 冷却 CMOS（FITS, OSC / Mono）は主要な運用対象。後付けにすると Mono のフィルター別処理やセンサー種別の分岐で設計をやり直すことになる | Phase 1 から DSLR RAW と CMOS FITS の両方、OSC と Mono の両方を対象にする。センサー種別は FITS ヘッダ（`BAYERPAT`）から自動判定し、手動上書きも可能にする |

---

## 3. 技術的前提（調査で確認済み）

### 環境

| 項目 | 値 |
|---|---|
| Siril | 1.4.4 (`/Applications/Siril.app`) |
| Siril 同梱 Python | 3.12.9（`Siril.app/Contents/Frameworks/Python.framework`） |
| venv | `~/Library/Application Support/org.siril.Siril/siril/venv`（numpy 2.2.5 のみ。PyQt6 は未インストール → `ensure_installed` で初回に自動導入） |
| sirilpy | 1.0.25（`.python_module/sirilpy`） |
| ユーザースクリプト置き場 | `~/Library/Application Support/org.siril.Siril/scripts`（未作成。`config.1.4.ini` の `script_path` に登録済み） |
| 公式スクリプト参考実装 | `siril-scripts/preprocessing/Naztronomy-OSC_PP.py`（PyQt6, 1926 行） |

### 使用する sirilpy API

| メソッド | 用途 |
|---|---|
| `SirilInterface.connect()` / `disconnect()` | 接続 |
| `cmd(*args)` | Siril コマンド送信。失敗時 `CommandError`。処理スレッド使用中は `ProcessingThreadBusyError` |
| `log(msg, LogColor)` | Siril ログへ出力（1022 byte 上限） |
| `update_progress(msg, 0.0〜1.0)` / `reset_progress()` | Siril 側プログレスバー |
| `get_siril_wd()` / `get_siril_configdir()` | 既定の作業ディレクトリ、プリセット保存先 |
| `is_cli()` | ヘッドレス実行判定（将来のバッチモード用） |
| `error_messagebox` / `confirm_messagebox` | Siril 側のダイアログ |
| `ensure_installed("PyQt6", "astropy", "exifread")` | 依存導入。バージョン指定は `>=` のみ使用（公式ルール） |

### 使用する Siril コマンド（`siril-cli` の `help` で 1.4.4 の構文を確認済み）

```
requires 1.4.0
cd <dir>
setext fit
set32bits
convert <basename> [-debayer] [-out=<dir>]        # CR2/FITS → FITS 連番。FITS なら symlink、CR2 は実変換
link    <basename> [-date] [-out=<dir>]           # FITS 専用の convert
calibrate <seq> [-bias=] [-dark=] [-flat=] [-cc=dark [siglo sighi] | -cc=bpm file]
                [-cfa] [-debayer] [-equalize_cfa] [-opt[=exp]] [-prefix=]
register <seq> -2pass [-minpairs=] [-maxstars=] [-transf=] [-disto=]
seqapplyreg <seq> [-interp=] [-framing=] [-drizzle [-pixfrac=] [-kernel=] [-flat=]] [-scale=]
                  [-filter-fwhm=] [-filter-wfwhm=] [-filter-round=] [-filter-bkg=]
                  [-filter-nbstars=] [-filter-quality=] [-filter-included]
stack <seq> rej <type> <lo> <hi> [-norm=addscale|mulscale|add|mul|-nonorm] [-fastnorm]
                 [-weight=noise|wfwhm|nbstars] [-feather=] [-rgb_equal] [-output_norm]
                 [-32b] [-maximize] [-rejmap] [-filter-*] [-out=]
merge <seq1> <seq2> ... <out_seq>                 # 複数セッションの pp_ を結合
seqheader <seq> EXPTIME ISOSPEED ... [-out=csv]   # 変換後のメタデータ取得
unselect <seq> from to
load / mirrorx -bottomup / save / close
```

Rejection 種別: `p`(percentile) `s`(sigma) `m`(median) `w`(winsorized, 既定) `l`(linear) `g`(GESD) `a`(MAD)。
公式推奨: 少数枚 → Winsorized / Sigma、50 枚超 → GESD、勾配の強い大量枚 → Linear Fit。

### 制約

- Siril の処理スレッドは 1 本。コマンドは **必ず直列**で送る（並列実行不可）
- 実行中の Siril コマンドを API から強制停止する手段は無い。中止は **コマンド境界**で行う（Siril 本体の Stop ボタンは併用可）
- Drizzle 時は入力を CFA のまま保つ（`calibrate` に `-debayer` を付けない）。Mono ではこの制約は無い
- `merge` は同一サイズ・同一種別のシーケンスのみ結合可能
- FITS 入力の `convert` は symlink を張るだけで実変換しない（`-debayer` を付けた場合を除く）。CMOS 運用ではディスク消費が DSLR より少ない
- CMOS はアンプグローがあるため Dark optimization（`-opt`）は既定 OFF。DSLR の Bias 固定値相当として、CMOS では `-bias="=64*$OFFSET"`（FITS の `OFFSET` キーワード参照）が使える

---

## 4. 機能要件

### MVP（Phase 1）で必ず入れるもの

- [x] 入力形式: DSLR RAW（CR2 / CR3 / NEF / ARW 等、Siril の libraw 対応範囲）と FITS（CMOS 撮影ソフト出力）の両方
- [x] センサー種別: OSC / Mono を FITS ヘッダ（`BAYERPAT`）と拡張子から自動判定、手動で上書き可能。判定結果で `-cfa` / `-debayer` / `-equalize_cfa` の付与を切り替える
- [x] Mono: `FILTER` ヘッダでフィルター別にグループ化し、フィルターごとに Flat を対応させて 1 本ずつスタック
- [x] Light / Dark / Flat / Bias の投入（ファイル追加・フォルダ追加・ドラッグ&ドロップ・クリア・個別削除）
- [x] FITS の `IMAGETYP` による自動振り分け（「まとめて追加」に放り込むと Light / Dark / Flat / Bias に分類。RAW は種別を持たないので手動）
- [x] 各種別で「フレームから作成」または「既存マスター FITS を指定」を選択
- [x] Bias は「フレーム / 既存マスター / 固定値 / `$OFFSET` 参照 / なし」。Flat 用に Dark Flat（フラットダーク）も指定可能
- [x] 基本グループ化: 露出 / ISO・Gain / Filter / Binning / 画像サイズで Light を分け、Dark・Flat・Bias を各グループに自動マッチ（結果は Frames タブに表示し手動で上書き可能）
- [x] 作業ディレクトリの指定（既定: Siril の現在の作業ディレクトリ配下 `Kasane_<日時>/`）
- [x] symlink による入力ステージング（失敗時コピー）
- [x] Calibration: Dark / Flat / Bias の適用、Cosmetic Correction（`-cc=dark` + sigma）、CFA、equalize_cfa、Dark optimization
- [x] Registration: 2-pass、minpairs、maxstars、interp、transf
- [x] 品質フィルタ: wFWHM / roundness / 星数（`k` 倍・`%`・実値）
- [x] Stacking: rejection 種別 + sigma、normalization、weight、rgb_equal、output_norm、32bit
- [x] Drizzle: ON/OFF、scale、pixfrac、kernel
- [x] 出力: 結果ファイル名、DSLR 用 `mirrorx -bottomup`、中間ファイルの削除
- [x] 実行: QThread ワーカー、進捗バー、GUI 内ログ（Siril ログにも同時出力）、中止ボタン
- [x] Analyze: 枚数・推定ディスク使用量・警告（Light が無い、Flat と Light のサイズ不一致など）の事前表示
- [x] プリセット保存・読込（JSON、Siril 設定ディレクトリ配下）
- [x] 最後のプロジェクト状態（ファイルリスト含む）の自動復元

### Phase 2 以降

- 複数セッション（撮影日 / フォルダ）: セッションごとに Flat / Dark を対応させて Calibration → `merge` → 一括 Registration / Stack
- グループ化の高度化: 露出・温度の許容差設定、マッチング優先順位のカスタマイズ
- Dark / Flat マスターライブラリ（作ったマスターを露出・温度・ISO タグ付きで保存し次回自動マッチ）
- ヘッドレスバッチモード（`pyscript Kasane.py project.json`）
- 生成した Siril コマンド列を `.ssf` としてエクスポート（デバッグ・再現用）
- 実行後の品質レポート（登録データから FWHM / 星数のグラフ、除外フレーム一覧）

### やらないこと

- Siril 本体に無い処理（独自の画像処理アルゴリズム）
- 後処理（背景抽出、SPCC、ストレッチ）。前処理の完了で終わる
- Windows / Linux の動作保証（構造上は可能だが最初は macOS のみ検証）

---

## 5. アーキテクチャ

### ファイル構成

Siril のスクリプトメニューは `script_path` 直下の `.py` を列挙する。
配布用は単一ファイルが公式推奨だが、個人用途では保守性を優先し **パッケージ構成 + 薄いランチャー**にする。

```
kasane/                         ← このリポジトリ
├── PLAN.md                         ← 本書
├── README.md
├── Kasane.py                    ← ランチャー（Siril の scripts/ に置く。sys.path に隣の kasane/ を追加して main() を呼ぶ）
├── kasane/                     ← 本体パッケージ（scripts/ に一緒に置く）
│   ├── __init__.py
│   ├── main.py                     ← エントリ。接続・ensure_installed・QApplication 起動
│   ├── model/
│   │   ├── project.py              ← Project / FrameSet / FrameInfo / Group / Session（dataclass, JSON 直列化）
│   │   ├── settings.py             ← CalibrationSettings / RegistrationSettings / StackingSettings / DrizzleSettings / OutputSettings
│   │   └── presets.py              ← プリセットの保存・読込
│   ├── metadata/
│   │   ├── reader.py               ← FrameInfo 抽出の入口（拡張子で振り分け）。センサー種別判定もここ
│   │   ├── fits_reader.py          ← astropy（EXPTIME, GAIN, OFFSET, ISOSPEED, FILTER, XBINNING, CCD-TEMP, SET-TEMP,
│   │   │                              NAXIS1/2, DATE-OBS, IMAGETYP, BAYERPAT, INSTRUME）
│   │   └── raw_reader.py           ← exifread（CR2/CR3/NEF/ARW: 露出, ISO, 撮影日時, 画像サイズ。常に OSC 扱い）
│   ├── grouping.py                 ← FrameInfo → Group の分類と Dark/Flat/Bias マッチング（Phase 1）、Session（Phase 2）
│   ├── staging.py                  ← 作業ディレクトリ生成、symlink / copy、クリーンアップ
│   ├── pipeline/
│   │   ├── planner.py              ← Project + Settings → Step のリスト（Siril コマンド列）を生成。**Siril に接続せず純粋関数**
│   │   ├── steps.py                ← Step(dataclass: name, cwd, args, weight, expects_output)
│   │   └── runner.py               ← Step を順に siril.cmd() で実行。進捗・ログ・中止をコールバックで通知
│   ├── gui/
│   │   ├── main_window.py          ← QMainWindow。タブ + ログ + RUN/Analyze/中止
│   │   ├── frames_tab.py           ← 4 種別の FrameListWidget（D&D 対応）
│   │   ├── calibration_tab.py
│   │   ├── registration_tab.py
│   │   ├── stacking_tab.py
│   │   ├── output_tab.py
│   │   ├── widgets.py              ← FrameListWidget, PathPicker, LogView など共通部品
│   │   └── worker.py               ← QThread ワーカー（runner をラップしシグナルに変換）
│   └── util/
│       ├── log.py                  ← GUI ログと siril.log の二重出力
│       └── diskspace.py            ← 使用量見積もり
├── tests/
│   ├── test_planner.py             ← 設定 → コマンド列のスナップショットテスト（Siril 不要）
│   ├── test_grouping.py
│   ├── test_metadata.py
│   └── fixtures/                   ← 小さな FITS / CR2 ヘッダのサンプル
└── tools/
    ├── install.sh                  ← scripts/ へ symlink を張る開発用スクリプト
    └── build_single_file.py        ← （任意）配布用に単一 .py へ結合
```

### 設計方針

1. **planner（コマンド生成）と runner（実行）を分離する**
   planner は Siril に接続しないので、ユニットテストで「この設定ならこのコマンド列」を検証できる。`.ssf` エクスポートもここから作れる。
2. **GUI は model を編集するだけ**。RUN 時に model を丸ごとワーカーへ渡す。
3. **Siril コマンドは全て相対パスで発行し、`cd` を明示する**。作業ディレクトリ構造を planner が一元管理する。
4. **中止フラグはコマンド境界でチェック**。runner は各 Step 前にフラグを見て `Cancelled` 例外で抜ける。
5. **失敗時は必ず理由をログに残し、作業ディレクトリは消さない**（再実行・手動リカバリのため）。

### 作業ディレクトリ構造

```
<work_root>/Kasane_20260911_2130/
├── project.json                 ← 実行時の設定と入力一覧（再現用）
├── commands.ssf                 ← 実際に発行したコマンド列
├── input/                       ← symlink（または copy）
│   ├── lights/   (Phase 2: lights/<session>/<group>/)
│   ├── darks/
│   ├── flats/
│   └── biases/
├── process/                     ← convert 出力と中間シーケンス（bias_*, dark_*, flat_*, pp_flat_*, light_*, pp_light_*, r_pp_light_*）
├── masters/                     ← bias_stacked.fit / dark_stacked.fit / pp_flat_stacked.fit
├── output/
│   ├── result_<target>_<livetime>s.fit
│   └── quality.csv              ← 登録データ（Phase 2）
└── log.txt
```

---

## 6. パイプライン設計（Phase 1: 単一セッション、OSC / Mono）

planner が生成する Step 列。`[ ]` は設定で省略される部分。
以下は 1 グループ分。Mono でフィルターが複数ある場合はグループごとにこの列を繰り返し、`process/<group>/` に分けて出力する。

センサー種別による分岐:

| フラグ | OSC（DSLR RAW / CMOS OSC FITS） | Mono |
|---|---|---|
| `calibrate -cfa` | 付ける | 付けない |
| `calibrate -equalize_cfa` | 付ける（設定で OFF 可） | 付けない |
| `calibrate -debayer` | Drizzle OFF のとき付ける | 付けない |
| `stack -rgb_equal` | 付ける（設定で OFF 可） | 付けない |
| `seqapplyreg -drizzle` | CFA のまま入力 | そのまま入力可 |
| Flat のグループ化 | 不要 | `FILTER` ごと |

```
requires 1.4.0
setext fit
set32bits
cd <work>/input/biases  ; convert bias  -out=../../process         (Bias がフレームのとき)
cd <work>/process       ; stack bias rej w 3 3 -nonorm -out=../masters/bias_stacked
cd <work>/input/darks   ; convert dark  -out=../../process         (Dark がフレームのとき)
cd <work>/process       ; stack dark rej w 3 3 -nonorm -out=../masters/dark_stacked
cd <work>/input/flats   ; convert flat  -out=../../process         (Flat がフレームのとき)
cd <work>/process       ; calibrate flat [-bias=../masters/bias_stacked | -bias="=2048" | -bias="=64*$OFFSET" | -dark=../masters/darkflat_stacked]
                        ; stack pp_flat rej w 3 3 -norm=mul -out=../masters/pp_flat_stacked
cd <work>/input/lights  ; convert light -out=../../process
cd <work>/process       ; calibrate light [-dark=...] [-flat=...] [-bias=...]
                                          [-cc=dark <siglo> <sighi>] [-opt]
                                          [-cfa] [-equalize_cfa]        ← OSC のときだけ
                                          [-debayer]                    ← OSC かつ Drizzle OFF のときだけ
                        ; register pp_light -2pass [-minpairs=N] [-maxstars=N] [-transf=...]
                        ; seqapplyreg pp_light [-interp=...] [-framing=...]
                                          [-drizzle -scale=S -pixfrac=P -kernel=K [-flat=../masters/pp_flat_stacked]]
                                          [-filter-wfwhm=Xk] [-filter-round=Yk] [-filter-nbstars=Z%]
                        ; stack r_pp_light rej <type> <lo> <hi> -norm=addscale [-weight=...] [-rgb_equal ← OSC のみ]
                                          -output_norm -32b -filter-included -out=../output/result[_<filter>]
cd <work>/output        ; load result ; [mirrorx -bottomup] ; save result_<target>_$LIVETIME:%d$s
close
[中間ファイル削除: process/ 内の light_*, pp_light_*, r_pp_light_*]
```

補足:

- 既存マスターが指定された種別は `convert` / `stack` を省き、`masters/` に symlink を張ってパスだけ使う
- Flat のキャリブレーションは「Bias（フレーム / マスター / 固定値 / `$OFFSET`）」または「Dark Flat」から選ぶ。CMOS では Dark Flat または `$OFFSET` を既定、DSLR では固定値を既定にする
- Dark 露出と Light 露出が異なる場合、DSLR では `-opt` を推奨として警告する。CMOS ではアンプグローのため露出一致の Dark を用意するよう警告する（`-opt` は明示指定時のみ）
- `mirrorx -bottomup` は DSLR RAW のときだけ既定 ON（FITS は撮影ソフトの向きをそのまま保つ）
- `-filter-*` は `seqapplyreg` に付ける（r_ 生成枚数が減り時間とディスクを節約）。`stack` 側は `-filter-included` のみ
- Dark / Flat / Bias の rejection は Light と別設定にする（枚数が少ないので既定 Winsorized 3/3）

### グループ化とマッチング（Phase 1: 単一セッション）

Light のグループキー: `(露出, ISO/Gain, Filter, Binning, 画像サイズ)`。
グループごとに以下の規則で Dark / Flat / Bias を割り当てる（WBPP 準拠）:

- Dark: 露出 一致（許容差設定可）> ISO/Gain 一致 > 温度 最近傍 > Binning 一致
- Flat: Filter 一致 > Binning 一致 > 画像サイズ 一致
- Bias / Dark Flat: ISO/Gain 一致 > Binning 一致
- マッチしない場合は Analyze で警告し、Frames タブで手動割当てを上書きできる
- DSLR は Filter / Gain / 温度が取れないので、露出と ISO と画像サイズのみで判定する

### Phase 2: 複数セッション

```
for session in sessions:                        # 撮影日 または フォルダ
    for group in session.light_groups:          # 露出 × ISO/Gain × Filter × Bin
        masters を session/group に対応させて calibrate → process/<session>/<group>/pp_light
merge process/s1/g1/pp_light process/s2/g1/pp_light ... process/merged/pp_light_g1
register / seqapplyreg / stack  (グループごとに 1 本の結果)
```

Flat のマッチングに「セッション一致」を最優先として追加する。

---

## 7. GUI 設計

### 画面構成（PyQt6, QMainWindow, 約 1000×760）

```
┌─ Kasane ─────────────────────────────────────────────────────────────┐
│ プリセット: [ EOS6D 標準 ▼ ] [保存] [削除]     作業フォルダ: [.../siril ▾] [参照] │
├───────────────────────────────────────────────────────────────────────────┤
│ [Frames] [Calibration] [Registration] [Stacking] [Output]                  │
│ ┌ Frames ───────────────────────────────────────────────────────────────┐ │
│ │ センサー: (•) 自動判定 → OSC (RGGB)  ( ) OSC  ( ) Mono    [まとめて追加] │ │
│ │ Light  128 枚  [+ファイル] [+フォルダ] [クリア]                          │ │
│ │ ┌────────────────────────────────────────────────────────┐            │ │
│ │ │ ▼ 180s / Gain100 / Ha / 1x1  (64 枚)                    │ ← グループ │ │
│ │ │     Light_0001.fit   180s  G100  -10.0℃  2026-09-10     │   ツリー   │ │
│ │ │ ▼ 180s / Gain100 / OIII / 1x1 (64 枚)                   │   D&D 受付 │ │
│ │ └────────────────────────────────────────────────────────┘            │ │
│ │ Dark    30 枚  (•) フレーム ( ) マスター [                    ] [参照] │ │
│ │ Flat    80 枚  (•) フレーム ( ) マスター    → Ha: 40  OIII: 40         │ │
│ │ Bias     0 枚  ( ) フレーム ( ) マスター ( ) 固定値 (•) $OFFSET ( ) なし │ │
│ │ Dark Flat 0 枚 ( ) フレーム ( ) マスター                               │ │
│ │ 割当て: Light[180s/G100/Ha] ← Dark[180s/G100] Flat[Ha] Bias[$OFFSET]  ✓ │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────────────────┤
│ ログ                                                                       │
│ ┌────────────────────────────────────────────────────────────────────────┐ │
│ │ [21:30:12] convert light -out=../../process                           │ │
│ │ [21:31:40] 128 files converted                                        │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ ████████████░░░░░░░░ 62%  register pp_light -2pass         [Analyze] [RUN] [中止] │
└───────────────────────────────────────────────────────────────────────────┘
```

### 各タブの項目

| タブ | 項目 |
|---|---|
| Frames | 上記。Light はグループ別ツリー表示、各グループへの Dark / Flat / Bias 割当てを表示し右クリックで上書き。「まとめて追加」は FITS の `IMAGETYP` で自動振り分け。各リストは右クリックで「選択を削除」「Finder で表示」 |
| Calibration | Dark 適用 / Flat 適用 / Flat のキャリブレーション方式（Bias / Dark Flat）/ Bias 方式 / Cosmetic Correction (ON, siglo, sighi) / equalize_cfa（OSC のみ有効）/ Dark optimization (off / on / exp、CMOS では既定 off) / マスター用 rejection |
| Registration | 2-pass（既定 ON）/ transf / minpairs / maxstars / interp / clamping / 品質フィルタ 3 種（有効化 + 値 + 単位 k/%/実値） |
| Stacking | Drizzle (ON, scale, pixfrac, kernel, flat 重み) / rejection 種別 + lo/hi / normalization / fastnorm / weight / rgb_equal（OSC のみ有効）/ output_norm / feather / 32bit |
| Output | 結果ファイル名テンプレート（Mono は `_<filter>` を自動付与）/ mirrorx（DSLR のみ既定 ON）/ 中間ファイル削除 / commands.ssf 出力 / 完了後に結果を Siril で開く |

### スレッド構成

```
GUI(main thread) ──RUN──▶ PipelineWorker(QThread)
                              │ run(project, settings)
                              │   planner.build_steps()
                              │   runner.execute(steps, on_progress, on_log, is_cancelled)
                              │       └─ siril.cmd(...)   ← 直列
                              ▼
   signals: progress(float, str) / log(str, level) / finished(result) / failed(err)
```

- `siril.cmd()` はワーカースレッドからのみ呼ぶ。GUI スレッドでは呼ばない
- ログは GUI と `siril.log()` の両方に出す
- RUN 中はタブを無効化し、中止ボタンのみ有効

### 状態の永続化

| 何を | どこに |
|---|---|
| プリセット（設定のみ） | `<siril configdir>/kasane/presets/<name>.json` |
| 直前のプロジェクト（設定 + ファイルリスト + 作業フォルダ） | `<siril configdir>/kasane/last_project.json` |
| 実行時スナップショット | `<work>/project.json`, `<work>/commands.ssf` |

---

## 8. データモデル

```python
@dataclass
class FrameInfo:
    path: Path
    kind: Literal["light", "dark", "flat", "bias", "darkflat"]
    source: Literal["raw", "fits"]         # DSLR RAW か FITS か
    sensor: Literal["osc", "mono", "unknown"]
    bayer_pattern: str | None              # RGGB など（FITS の BAYERPAT、RAW は libraw 任せで None）
    exposure: float | None                 # 秒
    iso_or_gain: float | None              # DSLR: ISO、CMOS: GAIN
    offset: float | None                   # CMOS の OFFSET（Bias 固定値の算出用）
    filter: str | None                     # Mono のフィルター名。OSC は None
    binning: int | None
    temperature: float | None              # CCD-TEMP
    width: int | None
    height: int | None
    date_obs: datetime | None
    instrument: str | None                 # INSTRUME / EXIF Model
    session_key: str | None                # Phase 2: 撮影日（正午区切り）またはフォルダ

@dataclass(frozen=True)
class GroupKey:
    exposure: float | None
    iso_or_gain: float | None
    filter: str | None
    binning: int | None
    size: tuple[int, int] | None

@dataclass
class MasterSource:
    mode: Literal["frames", "master_file", "constant", "offset_keyword", "none"]
    frames: list[FrameInfo] = field(default_factory=list)
    master_path: Path | None = None
    constant: float | None = None          # Bias 固定値（DSLR 向け）

@dataclass
class LightGroup:
    key: GroupKey
    frames: list[FrameInfo]
    dark: MasterSource                     # 自動マッチ結果。手動上書き可
    flat: MasterSource
    bias: MasterSource
    darkflat: MasterSource

@dataclass
class Project:
    sensor_override: Literal["auto", "osc", "mono"]
    groups: list[LightGroup]               # Light はグループ単位で保持
    dark_pool: list[FrameInfo]             # 投入された全 Dark / Flat / Bias / DarkFlat（マッチングの母集団）
    flat_pool: list[FrameInfo]
    bias_pool: list[FrameInfo]
    darkflat_pool: list[FrameInfo]
    work_root: Path
    settings: Settings                     # Calibration / Registration / Stacking / Drizzle / Output
    schema_version: int = 1
```

Phase 2 で `Session` を追加し、`groups` をセッション配下に持たせる。
JSON は `schema_version` を持たせ、後方互換のマイグレーションを書く。

---

## 9. 実装フェーズ

### 進捗（2026-09-11 時点）

| フェーズ | 状態 | 備考 |
|---|---|---|
| Phase 0 スパイク | 完了 | パッケージ構成 + ランチャーで `__file__` / 隣接 import / argv すべて OK。`ensure_installed("PyQt6", "exifread")` は約 8 秒で成功 |
| Phase 1 MVP | 実装完了・Siril 本体で統合テスト済み | 合成 FITS（OSC 8 枚 + Mono Ha/OIII 各 6 枚）で `siril-cli` からヘッドレス実行し、マスター作成 → calibrate → register -2pass → seqapplyreg → stack → 結果保存まで成功。GUI はオフスクリーンのスモークテスト（投入 → Analyze → dry-run 実行）で確認 |
| 実データ検証 | 未 | EOS 6D の CR2（外付け HDD 上）と実機 CMOS の FITS はまだ通していない。Scripts メニューからの GUI 起動も実機 Siril での確認待ち |
| Phase 2 複数セッション | 実装完了・統合テスト済み | セッションはフォルダ（種別フォルダを読み飛ばした親）または撮影日（正午区切り）で自動判定。セッション × 条件でキャリブレーションし、同じ条件は `merge` で結合して 1 本にスタック。合成 2 夜データで `siril-cli` 実行成功（12 枚 → 360s） |
| 名称変更 | 完了 | ユーザー要望で SirilWBPP → **Kasane（重ね）** に改名（2026-09-11） |
| Phase 3 品質・利便性 | 実装完了・統合テスト済み | 品質レポート（`.seq` の登録データと `r_` 側の採否から CSV + ログ要約 + GUI ダイアログ）、マスターライブラリ（保存 / 自動マッチ / Library タブ）、スタック方式の選択（rej / med / sum / max / min）。ライブラリだけで再キャリブレーションする統合テストと、フィルタで 5 枚除外されるレポートを `siril-cli` で確認 |
| Phase 4 仕上げ | 未着手 | 単一ファイル化、他 OS 確認 |

開発上の注意:
- Siril 同梱 Python（`Siril.app/Contents/Frameworks/Python.framework`）は端末から直接起動すると SIGKILL されるため、ユニットテストは `.venv`（pyenv の Python 3.11）で実行する
- Siril 本体を使うテストは `siril-cli -s <ssf>` から `pyscript Kasane.py --project <json>` を呼ぶ
- FITS ヘッダは astropy を使わず純 Python で読む（依存を減らし起動を速くするため）

### Phase 0: スパイク（半日）

目的: 前提の検証。ここで NG が出たら設計を直す。

1. `scripts/` に最小の PyQt6 スクリプトを置き、Siril の Scripts メニューに出ること・起動することを確認
2. ランチャー + パッケージ構成で隣のパッケージが import できることを確認（`__file__` から `sys.path` 追加）
3. `ensure_installed("PyQt6", "astropy", "exifread")` の所要時間と成功を確認
4. QThread から `siril.cmd("cd", ...)` / `siril.cmd("convert", ...)` を投げて動くこと、GUI が固まらないことを確認
5. symlink した CR2 と FITS を `convert` が読めることを確認（`/Volumes/...` 外付け HDD 上の実データで）。FITS 側は symlink の symlink になるので特に確認
6. `exifread` で CR2 の露出 / ISO / 撮影日時が取れること、`astropy` で CMOS FITS の `GAIN` / `OFFSET` / `FILTER` / `BAYERPAT` / `IMAGETYP` が取れることを確認（手持ちの撮影ソフト出力で実際のキーワード名を確認）

### Phase 1: MVP — 単一セッション、DSLR + CMOS、OSC + Mono（3〜4 日）

1. `model/` と `metadata/`（FITS / RAW 両対応、センサー判定）を先に書き、`tests/test_metadata.py` で検証
2. `grouping.py`（グループキー生成と Dark / Flat / Bias マッチング）を `tests/test_grouping.py` で検証
3. `pipeline/planner.py` を書き、`tests/test_planner.py` で以下を確認
   - OSC / Drizzle OFF: 公式 `OSC_Preprocessing.ssf` と同等のコマンド列
   - OSC / Drizzle ON: 公式 `OSC_Preprocessing_BayerDrizzle.ssf` と同等
   - Mono / 単一フィルター: 公式 `Mono_Preprocessing.ssf` と同等
   - Mono / 複数フィルター: フィルター数ぶんの列が出て Flat が正しく対応する
4. `staging.py`（symlink / copy / クリーンアップ、グループ別ディレクトリ）
5. `pipeline/runner.py` + `gui/worker.py`
6. GUI: Frames タブ（D&D、グループツリー、割当て表示）→ 他タブ → ログ・進捗・中止
7. Analyze（枚数、サイズ整合性、露出不一致警告、マッチ失敗警告、ディスク見積もり）
8. プリセット / last_project の保存復元
9. 実データで通しテスト: EOS 6D（2026-09-10 のアイリス星雲）と CMOS の FITS データ（OSC と Mono の両方）。公式スクリプトの結果と比較

### Phase 2: 複数セッション（2 日）

1. `Session` モデルの追加と `session_key` の導出（撮影日 / フォルダ）
2. Frames タブにセッション階層を追加、セッション別 Flat の割当て
3. planner をセッション対応に拡張（`merge` 利用）

### Phase 3: 品質・利便性（1〜2 日）

1. 実行後レポート（`seqheader` / 登録データ CSV、除外フレーム一覧）
2. `.ssf` エクスポート、ヘッドレスバッチモード
3. マスターライブラリ

### Phase 4: 仕上げ

1. エラーメッセージの整備、ドキュメント（README、使い方）
2. 単一ファイル結合スクリプト（必要なら）
3. Windows / Linux での動作確認（任意）

---

## 10. テスト計画

| 種類 | 内容 | Siril 必要 |
|---|---|---|
| ユニット | planner: 設定の組合せ → コマンド列（OSC / Mono、Drizzle 有無、Bias 方式 5 通り、Dark Flat、マスター指定、フィルタ単位、複数フィルター） | 不要 |
| ユニット | grouping: 露出・ISO/Gain・Filter・Bin からのグループ化、Dark / Flat / Bias マッチング、DSLR のメタデータ欠損時の挙動 | 不要 |
| ユニット | metadata: FITS（OSC / Mono、複数の撮影ソフトのキーワード差）/ CR2 のヘッダ読み取り、センサー判定（fixtures） | 不要 |
| ユニット | staging: symlink 作成、コピーへのフォールバック、クリーンアップ | 不要 |
| 結合 | `siril-cli -s` で planner が出した `.ssf` を小さなテストデータに対して実行 | 必要 |
| 手動 | GUI からの通し実行、中止、再実行、プリセット | 必要 |

---

## 11. リスクと対応

| リスク | 対応 |
|---|---|
| Siril が `script_path` 直下の `.py` しか列挙せず、パッケージ構成が使えない | Phase 0 で確認。NG なら `tools/build_single_file.py` で単一ファイル化して配布 |
| PyQt6 の初回インストールが遅い / 失敗する | 初回起動時に進捗を Siril ログに出す。失敗時は手順を表示 |
| 外付け HDD（exFAT 等）で symlink が張れない | `os.symlink` 失敗時にコピーへフォールバック。Analyze でディスク見積もりを増やす |
| CR2 の EXIF から露出 / ISO が取れない機種 | `convert` 後に `seqheader` で補完する二段構え |
| 撮影ソフトごとに FITS キーワード名が違う（`GAIN` / `EGAIN`、`CCD-TEMP` / `CCDTEMP`、`FILTER` の表記揺れ、`IMAGETYP` の値が `Light Frame` / `LIGHT` など） | `fits_reader.py` にキーワードの別名表と正規化テーブルを持たせる。未知の値は `unknown` として手動指定に落とす |
| `BAYERPAT` が無い OSC FITS（撮影ソフトが書かない場合） | 自動判定は `unknown` にして UI で OSC / Mono を選ばせる。Siril 側の debayer 設定（`use_bayer_header`）に依存させない |
| 大量枚数（>1000 枚）でメモリ・時間 | Siril 側の制約。`setmem` / `setcpu` を Output タブで設定可能にする |
| 実行中のコマンドを止められない | 中止はコマンド境界。UI に「現在のコマンド完了後に停止します」と明示 |
| Siril 側の処理スレッドが使用中（`ProcessingThreadBusyError`） | RUN 前に検出して「Siril で処理中の作業を終えてください」と案内 |

---

## 12. 未決事項（実装しながら決める）

- UI 言語: 日本語を既定にする（ラベルは日本語、コマンド・ファイル名は英語）
- Bias 固定値の既定: EOS 6D の 14bit オフセット 2048 を 16bit スケールに直した値を Phase 0 の実測で決める。CMOS は `$OFFSET` 参照を既定にし、キーワードが無ければ Dark Flat を促す
- CMOS の実データ: 手持ちの撮影ソフト（N.I.N.A. / ASIAIR など）の FITS を Phase 0 で確認し、キーワード別名表の初期値を決める
- 結果ファイル名テンプレートの既定: `result_<target>_<livetime>s.fit`。`<target>` は Light の親フォルダ名から推定
- Phase 2 のセッション境界: 撮影日を正午区切りにするか、フォルダ単位にするか（両方対応し既定はフォルダ）
