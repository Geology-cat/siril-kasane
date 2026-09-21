# 変更履歴

## 1.2.0 (2026-09-22)

### Dark を使わないときの Flat の過補正を防止

- Dark の無いグループで Flat を使うとき、Bias を自動で Light に引くようにしました（Calibration タブ「Dark が無いときは Bias / RAW の黒レベルを自動で Light に引く」、既定 ON）
  - 投入・指定した Bias（フレーム / マスター / 固定値 / ライブラリ）があればそれを、無ければ DSLR RAW の EXIF から読んだ黒レベルを固定値（`-bias="=2048"` など）として使います
  - これまでは「Light に Bias を引く」をオンにしない限り Light に Bias が引かれず、黒レベル（オフセット）まで Flat で割られて周辺が明るく浮く過補正になっていました。Bias のマスターを指定していても、既存マスターの Flat を使う場合は Bias がどこにも使われていませんでした
  - 実例: Canon EOS 6D + 15 mm の 30 s / ISO 8000、23 枚、Dark・Bias なし。空の上端で中央に対する右端の明るさが 2.88 倍 → 1.12 倍
  - 引けるオフセットが無い場合は Analyze で警告し、Frames タブの Bias 列に「⚠ 過補正」と表示します
- RAW の黒レベルを読むようにしました（Canon: MakerNote の ColorData の PerChannelBlackLevel、DNG: BlackLevel）。exifread では読めないため TIFF 構造を直接解析します
- 既存マスターの Flat を使うときは Flat 用の Bias を用意しない / 「Flat 用の Bias がありません」と警告しないようにしました（既存マスターはそのまま使うため不要）

### 「すべてクリア」

- マスターファイルの指定（例: 既存のマスターフラット）、Bias の固定値、各種別のモード、センサー種別も初期状態に戻すようにしました
- 対象名と作業フォルダもクリアするようにしました

### その他

- 作業フォルダが空のときは Light のフォルダ内の `output/` を使うようにしました（`lights/` などの汎用名なら 1 つ上。対象名の推定と同じ）。これまでは起動時に Siril の作業ディレクトリを自動で入れていました
- Analyze の「Dark がありません（）」のように理由が空のとき括弧を出さないようにしました

## 1.1.1 (2026-09-14)

ドキュメントのみの更新です。機能の変更はありません。

- README に動作要件を追記: Python の別途インストールの要否（Windows / macOS は不要、Linux のディストリ版は python3-venv / python3-pip が必要）、初回起動時のみインターネット接続が必要なこと
- README に「うまく起動しないとき」を追加
- 単一ファイル版のヘッダにも同じ要件を記載

## 1.1.0 (2026-09-14)

- 非線形画像モード: JPEG / PNG / TIFF / HEIF / AVIF を Light に投入すると、キャリブレーション無しで位置合わせ → スタックできる
  - 星像が飽和していて FWHM を計測できない場合があるため、wFWHM / 真円度 / FWHM / 品質フィルタは自動で無効化（星数 / 背景フィルタは有効）
  - PNG / JPEG のヘッダから画像サイズを、JPEG / TIFF の EXIF から露出 / ISO / 撮影日時を読む
- Registration に「位置合わせしない」を追加（固定三脚の軌跡合成、位置合わせ済み画像向け）
- Output に「保存形式」を追加（FITS / 16bit TIFF / 両方）
- 露出が分からない入力では、結果のファイル名を積算秒ではなく枚数（`_8frames`）にする
- 品質レポートで FWHM を計測できなかったフレームを統計から除外し、件数を表示

## 1.0.0 (2026-09-11)

最初の公開版。

- Light / Dark / Flat / Bias / Dark Flat のドラッグ&ドロップ投入、FITS の IMAGETYP による自動振り分け
- DSLR RAW と CMOS FITS、OSC と Mono に対応。センサー種別は BAYERPAT から自動判定
- 露出 / Gain / Filter / Binning / サイズによる自動グループ化と Dark / Flat / Bias の自動割当て
- 複数夜のセッション対応（フォルダ / 撮影日で自動判定、セッションごとにキャリブレーションして merge）
- 2-pass レジストレーション + 品質フィルタ（wFWHM / 真円度 / 星数 など）
- スタック方式（rej / med / sum / max / min）、rejection、正規化、重み付け、Bayer Drizzle
- 品質レポート（CSV + GUI）、マスターライブラリ、プリセット、前回状態の復元
- ヘッドレス実行（`pyscript Kasane.py --project project.json`）
- 単一ファイル版の配布
