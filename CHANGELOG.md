# 変更履歴

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
