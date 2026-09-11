"""
実行前チェック（Analyze）

Project と設定の整合性を検査し、警告・エラーの一覧を返す。
error が 1 つでもあれば RUN できない。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..model import Project
from ..util.diskspace import estimate


class AnalyzeError(Exception):
    """error レベルの問題があり実行できない"""

    def __init__(self, issues: list["Issue"]):
        self.issues = [i for i in issues if i.level == "error"]
        super().__init__("実行前チェックでエラー: " + " / ".join(i.text for i in self.issues))


@dataclass
class Issue:
    level: str  # "error" | "warn" | "info"
    text: str

    @property
    def icon(self) -> str:
        return {"error": "✖", "warn": "⚠", "info": "ℹ"}[self.level]


def analyze(project: Project, work_root: Optional[Path]) -> list[Issue]:
    issues: list[Issue] = []
    s = project.settings
    err = lambda t: issues.append(Issue("error", t))  # noqa: E731
    warn = lambda t: issues.append(Issue("warn", t))  # noqa: E731
    info = lambda t: issues.append(Issue("info", t))  # noqa: E731

    if not project.lights:
        err("Light が投入されていません")
        return issues
    if work_root is None:
        err("作業フォルダが指定されていません")
    elif not work_root.parent.exists():
        err(f"作業フォルダの親が存在しません: {work_root.parent}")

    # センサー
    if project.sensor not in ("osc", "mono"):
        err("センサー種別を判定できません。Frames タブで OSC / Mono を指定してください")
    elif project.sensor_override == "auto":
        info(f"センサー種別: {'OSC（カラー）' if project.is_osc else 'Mono'}（自動判定）")

    # 入力形式の混在
    sources = {f.source for f in project.lights}
    if len(sources) > 1:
        warn("Light に RAW と FITS が混在しています。グループが分かれて別々にスタックされます")
    bad = [f for f in project.all_frames() if f.error]
    if bad:
        warn(f"メタデータを読めないファイルが {len(bad)} 件あります（例: {bad[0].name}: {bad[0].error}）。"
             "グループ化に使えないため、条件が同じか手動で確認してください")

    # Bias 方式
    if project.bias_mode == "offset_keyword" and project.is_raw:
        err("DSLR RAW には OFFSET キーワードが無いため「64 × $OFFSET」は使えません。固定値を指定してください")
    if project.bias_mode == "constant" and not project.is_raw:
        info("Bias を固定値で指定しています。CMOS では「64 × $OFFSET」または Dark Flat の利用を推奨します")

    # グループごとの割当て
    c = s.calibration

    def note_level(note: str):
        """ライブラリからの割当ては情報。不一致を含むときだけ警告"""
        if note.startswith("ライブラリ") and "不一致" not in note and "温度差" not in note:
            return info
        return warn

    for g in project.groups:
        prefix = f"[{g.group_id} {g.label}] "
        if c.use_dark:
            if not g.dark.is_available:
                warn(prefix + f"Dark がありません（{g.dark.note}）。Dark なしでキャリブレーションします")
            elif g.dark.note:
                note_level(g.dark.note)(prefix + f"Dark: {g.dark.note}")
                if "露出不一致" in g.dark.note:
                    if project.is_raw and c.dark_opt == "off":
                        info(prefix + "DSLR で露出の違う Dark を使う場合は Dark optimization（on / exp）を検討してください")
                    elif not project.is_raw:
                        info(prefix + "CMOS はアンプグローのため、露出の一致した Dark を推奨します")
        if c.use_flat:
            if not g.flat.is_available:
                warn(prefix + f"Flat がありません（{g.flat.note}）。Flat なしでキャリブレーションします")
            elif g.flat.note:
                note_level(g.flat.note)(prefix + f"Flat: {g.flat.note}")
            if c.flat_calib_mode == "bias" and g.flat.is_available and not g.bias.is_available:
                warn(prefix + "Flat 用の Bias がありません。Flat はキャリブレーションせずにスタックします")
            if c.flat_calib_mode == "darkflat" and g.flat.is_available and not g.darkflat.is_available:
                warn(prefix + f"Dark Flat がありません（{g.darkflat.note}）。Flat はキャリブレーションせずにスタックします")
            if g.darkflat.is_available and g.darkflat.note:
                note_level(g.darkflat.note)(prefix + f"Dark Flat: {g.darkflat.note}")
        if c.use_bias_for_light and not g.bias.is_available:
            warn(prefix + "Light 用の Bias がありません")
        if len(g.frames) < 3:
            warn(prefix + f"Light が {len(g.frames)} 枚しかありません。rejection スタックには 3 枚以上必要です")

    sessions = {g.session for g in project.groups if g.session}
    keys = {g.key for g in project.groups}
    if sessions:
        from ..model import session_label

        info(f"セッション {len(sessions)} 件（{', '.join(sorted(session_label(x) for x in sessions))}）を検出。"
             "セッションごとにキャリブレーションし、同じ条件の Light は結合して 1 本にスタックします")
    if len(keys) > 1:
        info(f"Light は条件の違う {len(keys)} グループに分かれ、それぞれ別にスタックされます")

    # Drizzle
    if s.drizzle.enabled and project.is_osc:
        info("Bayer Drizzle: Light はデベイヤーせずに処理します")
    if s.drizzle.enabled and len(project.lights) < 10:
        warn("Drizzle は枚数が少ないと効果が薄く、穴が残ることがあります（10 枚以上推奨）")

    # Cosmetic correction
    if c.cosmetic_enabled and not c.use_dark:
        info("Cosmetic Correction は Dark から不良画素を検出するため、Dark なしでは無効になります")

    # ディスク
    if work_root is not None:
        est = estimate(project, work_root)
        if est.free_bytes and not est.ok:
            warn("ディスク空き容量が不足する可能性があります: " + est.describe())
        else:
            info(est.describe())

    return issues
