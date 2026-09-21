"""
Light のオフセット（黒レベル / Bias）の扱いを決める

Flat 補正は (Light − オフセット) / Flat でなければならない。オフセットは Dark に含まれるので
Dark を引けば済むが、Dark が無いまま Flat で割ると、画面全体で一定のオフセットまで
周辺ほど大きく持ち上がり、Flat が過補正になる（DSLR の黒レベルは 14 bit 機でおよそ 2048 ADU、
暗い空では信号の大半を占める）。

そこで Dark が無く Flat を使うグループでは、次の順で Light に Bias を自動で引く
（設定 calibration.auto_bias_without_dark）:
  1. 投入 / 指定済みの Bias（フレーム・マスター・固定値）
  2. DSLR RAW なら EXIF から読んだ黒レベル（固定値 -bias="=<値>"）
どちらも無ければ警告する。planner（コマンド生成）と analyze（実行前チェック）で同じ判断を使う。
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional

from ..model import FrameInfo, LightGroup, MasterSource, Project


@dataclass
class LightOffset:
    """
    mode:
      not_needed : Flat を使わない（またはキャリブレーションしない）ので自動では何もしない
      dark       : Dark に含まれるオフセットで引ける
      bias       : ユーザー設定（Light に Bias を引く）どおりに Bias を引く
      auto_bias  : Dark が無いので、投入済みの Bias を自動で Light にも引く
      auto_black : Dark も Bias も無いので、RAW の黒レベルを固定値の Bias として自動で引く
      missing    : オフセットを引けないまま Flat で割る（過補正になる）
    """

    mode: str
    source: Optional[MasterSource] = None  # Light に引く Bias
    black_level: Optional[float] = None
    auto_disabled: bool = False  # missing のうち、自動補完を設定で切っているもの

    @property
    def applies_bias(self) -> bool:
        return self.mode in ("bias", "auto_bias", "auto_black")

    @property
    def is_auto(self) -> bool:
        return self.mode in ("auto_bias", "auto_black")


def group_black_level(frames: list[FrameInfo]) -> Optional[float]:
    """グループの Light の黒レベル（中央値を整数に丸める）。1 枚も読めていなければ None"""
    values = [f.black_level for f in frames if f.black_level is not None and f.black_level > 0]
    if not values:
        return None
    return float(round(median(values)))


def resolve_light_offset(project: Project, g: LightGroup) -> LightOffset:
    c = project.settings.calibration
    if project.is_nonlinear:
        return LightOffset("not_needed")
    if c.use_bias_for_light and g.bias.is_available:
        return LightOffset("bias", source=g.bias)
    if not (c.use_flat and g.flat.is_available):
        return LightOffset("not_needed")
    if c.use_dark and g.dark.is_available:
        return LightOffset("dark")
    if not c.auto_bias_without_dark:
        return LightOffset("missing", auto_disabled=True)
    if g.bias.is_available:
        return LightOffset("auto_bias", source=g.bias)
    if g.source == "raw":
        black = group_black_level(g.frames)
        if black is not None:
            src = MasterSource(mode="constant", constant=black, auto=True, note="RAW の黒レベル（EXIF）")
            return LightOffset("auto_black", source=src, black_level=black)
    return LightOffset("missing")


def describe_offset(off: LightOffset) -> str:
    """Analyze / コマンド生成のログに出す説明（not_needed / dark / bias は空文字）"""
    if off.mode == "auto_bias":
        return (f"Dark が無いため、Flat の過補正を防ぐために Bias（{off.source.describe() if off.source else ''}）を"
                "Light にも自動で引きます")
    if off.mode == "auto_black":
        return (f"Dark も Bias も無いため、Flat の過補正を防ぐために RAW の黒レベル {off.black_level:g} を"
                f"固定値の Bias として Light に自動で引きます（-bias=\"={off.black_level:g}\"）")
    if off.mode == "missing":
        base = ("Dark も Bias も無いまま Flat で割ります。黒レベル（オフセット）が残るため、周辺が明るく浮く過補正になります。"
                "Dark を投入するか、Bias（DSLR は固定値。Canon 14 bit 機は多くが 2048）を指定してください")
        if off.auto_disabled:
            base += "（Calibration タブの自動補完が無効です）"
        return base
    return ""
