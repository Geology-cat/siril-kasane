# 変更履歴

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
