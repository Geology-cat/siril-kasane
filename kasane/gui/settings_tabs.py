"""
Calibration / Registration / Stacking / Output タブ

各タブは Settings の該当 dataclass と双方向に同期する（load / store）。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..model import Settings
from ..model.settings import (
    DARK_OPT_MODES,
    DRIZZLE_KERNELS,
    FILTER_UNITS,
    FLAT_CALIB_MODES,
    FRAMING_TYPES,
    INTERP_TYPES,
    MIRRORX_MODES,
    NORMALIZATION_TYPES,
    OUTPUT_FORMATS,
    REGISTRATION_METHODS,
    REJECTION_TYPES,
    STACK_METHODS,
    TRANSFORM_TYPES,
    WEIGHT_TYPES,
    QualityFilter,
)
from .widgets import LabeledCombo, hint


def _dspin(lo: float, hi: float, step: float, decimals: int = 2) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    return s


def _spin(lo: int, hi: int, step: int = 1) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    return s


class CalibrationTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        box = QGroupBox("マスターの適用")
        form = QFormLayout(box)
        self.use_dark = QCheckBox("Dark を引く")
        self.use_flat = QCheckBox("Flat で割る")
        self.use_bias_light = QCheckBox("Light に Bias を引く（通常は不要。Dark に含まれます）")
        self.flat_mode = LabeledCombo(FLAT_CALIB_MODES)
        form.addRow(self.use_dark)
        form.addRow(self.use_flat)
        form.addRow(self.use_bias_light)
        form.addRow("Flat のキャリブレーション:", self.flat_mode)
        form.addRow(hint("CMOS は Dark Flat（Flat と同じ露出の Dark）を推奨。DSLR は Bias（固定値可）で十分です。"))
        lay.addWidget(box)

        box = QGroupBox("Cosmetic Correction（Dark から不良画素を検出）")
        form = QFormLayout(box)
        self.cc_enabled = QCheckBox("有効")
        self.cc_low = _dspin(0, 10, 0.5, 1)
        self.cc_high = _dspin(0, 10, 0.5, 1)
        form.addRow(self.cc_enabled)
        form.addRow("コールドピクセル σ（0 で無効）:", self.cc_low)
        form.addRow("ホットピクセル σ:", self.cc_high)
        lay.addWidget(box)

        box = QGroupBox("その他")
        form = QFormLayout(box)
        self.equalize_cfa = QCheckBox("Flat の RGB を均一化（equalize_cfa、OSC のみ）")
        self.dark_opt = LabeledCombo(DARK_OPT_MODES)
        form.addRow(self.equalize_cfa)
        form.addRow("Dark optimization:", self.dark_opt)
        form.addRow(hint("Dark optimization は露出や温度が違う Dark を使うときの係数補正。アンプグローのある CMOS では OFF を推奨。"))
        lay.addWidget(box)

        box = QGroupBox("マスター作成時の rejection")
        form = QFormLayout(box)
        self.m_rej = LabeledCombo(REJECTION_TYPES)
        self.m_low = _dspin(0, 10, 0.5, 1)
        self.m_high = _dspin(0, 10, 0.5, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("σ low"))
        row.addWidget(self.m_low)
        row.addWidget(QLabel("σ high"))
        row.addWidget(self.m_high)
        row.addStretch()
        form.addRow("方式:", self.m_rej)
        form.addRow("しきい値:", row)
        lay.addWidget(box)
        lay.addStretch()

    def load(self, s: Settings) -> None:
        c = s.calibration
        self.use_dark.setChecked(c.use_dark)
        self.use_flat.setChecked(c.use_flat)
        self.use_bias_light.setChecked(c.use_bias_for_light)
        self.flat_mode.set_value(c.flat_calib_mode)
        self.cc_enabled.setChecked(c.cosmetic_enabled)
        self.cc_low.setValue(c.cc_sigma_low)
        self.cc_high.setValue(c.cc_sigma_high)
        self.equalize_cfa.setChecked(c.equalize_cfa)
        self.dark_opt.set_value(c.dark_opt)
        self.m_rej.set_value(c.master_rej_type)
        self.m_low.setValue(c.master_sigma_low)
        self.m_high.setValue(c.master_sigma_high)

    def store(self, s: Settings) -> None:
        c = s.calibration
        c.use_dark = self.use_dark.isChecked()
        c.use_flat = self.use_flat.isChecked()
        c.use_bias_for_light = self.use_bias_light.isChecked()
        c.flat_calib_mode = self.flat_mode.value()
        c.cosmetic_enabled = self.cc_enabled.isChecked()
        c.cc_sigma_low = self.cc_low.value()
        c.cc_sigma_high = self.cc_high.value()
        c.equalize_cfa = self.equalize_cfa.isChecked()
        c.dark_opt = self.dark_opt.value()
        c.master_rej_type = self.m_rej.value()
        c.master_sigma_low = self.m_low.value()
        c.master_sigma_high = self.m_high.value()


class _FilterRow(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(label)
        self.value = _dspin(0, 10000, 0.5, 2)
        self.unit = LabeledCombo(FILTER_UNITS)
        lay.addWidget(self.enabled, 1)
        lay.addWidget(self.value)
        lay.addWidget(self.unit)

    def load(self, f: QualityFilter) -> None:
        self.enabled.setChecked(f.enabled)
        self.value.setValue(f.value)
        self.unit.set_value(f.unit)

    def store(self, f: QualityFilter) -> None:
        f.enabled = self.enabled.isChecked()
        f.value = self.value.value()
        f.unit = self.unit.value()


class RegistrationTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        box = QGroupBox("レジストレーション")
        form = QFormLayout(box)
        self.method = LabeledCombo(REGISTRATION_METHODS)
        self.method.currentIndexChanged.connect(lambda _i: self._method_changed())
        form.addRow("方式:", self.method)
        self.two_pass = QCheckBox("2-pass（最良の参照フレームを自動選択。推奨）")
        self.transf = LabeledCombo(TRANSFORM_TYPES)
        self.minpairs = _spin(0, 1000)
        self.maxstars = _spin(0, 2000, 100)
        self.interp = LabeledCombo(INTERP_TYPES)
        self.clamping = QCheckBox("クランプ（リンギング抑制）")
        self.framing = LabeledCombo(FRAMING_TYPES)
        form.addRow(self.two_pass)
        form.addRow("変換モデル:", self.transf)
        form.addRow("最小星ペア数（0 で既定）:", self.minpairs)
        form.addRow("最大星数（0 で既定、100〜2000）:", self.maxstars)
        form.addRow("補間:", self.interp)
        form.addRow(self.clamping)
        form.addRow("フレーミング:", self.framing)
        lay.addWidget(box)

        box = QGroupBox("品質フィルタ（条件を満たさないフレームを除外）")
        v = QVBoxLayout(box)
        v.addWidget(hint("k 倍: 中央値 + k×σ より悪いものを除外。%: 上位 n% を採用。実値: しきい値そのもの。"))
        self.f_wfwhm = _FilterRow("重み付き FWHM")
        self.f_round = _FilterRow("真円度（roundness）")
        self.f_nbstars = _FilterRow("星数")
        self.f_fwhm = _FilterRow("FWHM")
        self.f_quality = _FilterRow("品質（quality）")
        self.f_bkg = _FilterRow("背景レベル")
        for w in (self.f_wfwhm, self.f_round, self.f_nbstars, self.f_fwhm, self.f_quality, self.f_bkg):
            v.addWidget(w)
        self.filter_box = box
        lay.addWidget(box)
        lay.addStretch()
        self._method_changed()

    def _method_changed(self) -> None:
        on = self.method.value() == "global"
        for w in (self.two_pass, self.transf, self.minpairs, self.maxstars, self.interp, self.clamping, self.framing,
                  self.filter_box):
            w.setEnabled(on)

    def load(self, s: Settings) -> None:
        r = s.registration
        self.method.set_value(r.method)
        self.two_pass.setChecked(r.two_pass)
        self.transf.set_value(r.transf)
        self.minpairs.setValue(r.minpairs)
        self.maxstars.setValue(r.maxstars)
        self.interp.set_value(r.interp)
        self.clamping.setChecked(r.clamping)
        self.framing.set_value(r.framing)
        self.f_wfwhm.load(r.filter_wfwhm)
        self.f_round.load(r.filter_round)
        self.f_nbstars.load(r.filter_nbstars)
        self.f_fwhm.load(r.filter_fwhm)
        self.f_quality.load(r.filter_quality)
        self.f_bkg.load(r.filter_bkg)

    def store(self, s: Settings) -> None:
        r = s.registration
        r.method = self.method.value()
        r.two_pass = self.two_pass.isChecked()
        r.transf = self.transf.value()
        r.minpairs = self.minpairs.value()
        r.maxstars = self.maxstars.value()
        r.interp = self.interp.value()
        r.clamping = self.clamping.isChecked()
        r.framing = self.framing.value()
        self.f_wfwhm.store(r.filter_wfwhm)
        self.f_round.store(r.filter_round)
        self.f_nbstars.store(r.filter_nbstars)
        self.f_fwhm.store(r.filter_fwhm)
        self.f_quality.store(r.filter_quality)
        self.f_bkg.store(r.filter_bkg)


class StackingTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        box = QGroupBox("Drizzle")
        form = QFormLayout(box)
        self.drz_enabled = QCheckBox("Drizzle を使う（OSC は Bayer Drizzle: デベイヤーせずに処理）")
        self.drz_scale = _dspin(0.5, 3.0, 0.5, 1)
        self.drz_pixfrac = _dspin(0.1, 1.0, 0.1, 2)
        self.drz_kernel = LabeledCombo(DRIZZLE_KERNELS)
        self.drz_flat = QCheckBox("マスターフラットで入力ピクセルを重み付け")
        form.addRow(self.drz_enabled)
        form.addRow("スケール:", self.drz_scale)
        form.addRow("ピクセル比率（pixfrac）:", self.drz_pixfrac)
        form.addRow("カーネル:", self.drz_kernel)
        form.addRow(self.drz_flat)
        lay.addWidget(box)

        box = QGroupBox("スタック")
        form = QFormLayout(box)
        self.method = LabeledCombo(STACK_METHODS)
        self.method.currentIndexChanged.connect(lambda _i: self._method_changed())
        self.rej = LabeledCombo(REJECTION_TYPES)
        self.low = _dspin(0, 10, 0.5, 1)
        self.high = _dspin(0, 10, 0.5, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("σ low"))
        row.addWidget(self.low)
        row.addWidget(QLabel("σ high"))
        row.addWidget(self.high)
        row.addStretch()
        self.norm = LabeledCombo(NORMALIZATION_TYPES)
        self.fastnorm = QCheckBox("高速な正規化推定（fastnorm）")
        self.weight = LabeledCombo(WEIGHT_TYPES)
        self.rgb_equal = QCheckBox("RGB 背景を均一化（rgb_equal、OSC のみ）")
        self.output_norm = QCheckBox("結果を [0,1] に正規化（output_norm）")
        self.feather = _spin(0, 2000, 10)
        self.bits32 = QCheckBox("32bit で保存")
        self.rejmap = QCheckBox("Rejection マップも出力")
        form.addRow("方式:", self.method)
        form.addRow(hint("通常は Average with rejection。Median は枚数が少ないとき、Sum は測光用途、Max / Min は流星や軌跡向け"))
        form.addRow("Rejection:", self.rej)
        form.addRow("しきい値:", row)
        form.addRow(hint("枚数の目安: 〜6 枚 Percentile、少〜中 Winsorized / Sigma、50 枚超 GESD、勾配の強い大量枚 Linear Fit"))
        form.addRow("正規化:", self.norm)
        form.addRow(self.fastnorm)
        form.addRow("重み付け:", self.weight)
        form.addRow("フェザリング（px、0 で無効）:", self.feather)
        form.addRow(self.rgb_equal)
        form.addRow(self.output_norm)
        form.addRow(self.bits32)
        form.addRow(self.rejmap)
        lay.addWidget(box)
        lay.addStretch()
        self._method_changed()

    def _method_changed(self) -> None:
        """方式ごとに使えるオプションだけ有効にする（Siril の stack コマンドの仕様に合わせる）"""
        m = self.method.value()
        rej = m == "rej"
        norm_ok = m in ("rej", "med")
        for w in (self.rej, self.low, self.high, self.weight, self.feather, self.rejmap):
            w.setEnabled(rej)
        for w in (self.norm, self.fastnorm, self.rgb_equal):
            w.setEnabled(norm_ok)

    def load(self, s: Settings) -> None:
        d = s.drizzle
        self.drz_enabled.setChecked(d.enabled)
        self.drz_scale.setValue(d.scale)
        self.drz_pixfrac.setValue(d.pixfrac)
        self.drz_kernel.set_value(d.kernel)
        self.drz_flat.setChecked(d.use_flat)
        st = s.stacking
        self.method.set_value(st.method)
        self.rej.set_value(st.rej_type)
        self.low.setValue(st.sigma_low)
        self.high.setValue(st.sigma_high)
        self.norm.set_value(st.norm)
        self.fastnorm.setChecked(st.fastnorm)
        self.weight.set_value(st.weight)
        self.rgb_equal.setChecked(st.rgb_equal)
        self.output_norm.setChecked(st.output_norm)
        self.feather.setValue(st.feather)
        self.bits32.setChecked(st.bits32)
        self.rejmap.setChecked(st.rejmap)

    def store(self, s: Settings) -> None:
        d = s.drizzle
        d.enabled = self.drz_enabled.isChecked()
        d.scale = self.drz_scale.value()
        d.pixfrac = self.drz_pixfrac.value()
        d.kernel = self.drz_kernel.value()
        d.use_flat = self.drz_flat.isChecked()
        st = s.stacking
        st.method = self.method.value()
        st.rej_type = self.rej.value()
        st.sigma_low = self.low.value()
        st.sigma_high = self.high.value()
        st.norm = self.norm.value()
        st.fastnorm = self.fastnorm.isChecked()
        st.weight = self.weight.value()
        st.rgb_equal = self.rgb_equal.isChecked()
        st.output_norm = self.output_norm.isChecked()
        st.feather = self.feather.value()
        st.bits32 = self.bits32.isChecked()
        st.rejmap = self.rejmap.isChecked()


class OutputTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        box = QGroupBox("出力")
        form = QFormLayout(box)
        self.name_template = QLineEdit()
        self.format = LabeledCombo(OUTPUT_FORMATS)
        self.mirrorx = LabeledCombo(MIRRORX_MODES)
        self.cleanup = QCheckBox("完了後に中間ファイル（process/ と input/）を削除する")
        self.write_ssf = QCheckBox("実行するコマンド列を commands.ssf として保存する")
        self.open_result = QCheckBox("完了後に結果を Siril で開く")
        form.addRow("ファイル名テンプレート:", self.name_template)
        form.addRow(hint("使える変数: {target} 対象名、{filter} フィルター名、{filter_suffix} = \"_フィルター名\"（Mono 以外は空）、{group} グループ ID。"
                         "末尾に積算時間（例 _3600s）が自動で付きます。"))
        form.addRow("保存形式:", self.format)
        form.addRow("上下反転（mirrorx）:", self.mirrorx)
        form.addRow(self.cleanup)
        form.addRow(self.write_ssf)
        form.addRow(self.open_result)
        lay.addWidget(box)

        box = QGroupBox("Siril のリソース設定（0 で変更しない）")
        form = QFormLayout(box)
        self.setmem = _dspin(0, 2.0, 0.1, 2)
        self.setcpu = _spin(0, 256)
        form.addRow("メモリ使用比率（setmem）:", self.setmem)
        form.addRow("スレッド数（setcpu）:", self.setcpu)
        lay.addWidget(box)
        lay.addStretch()

    def load(self, s: Settings) -> None:
        o = s.output
        self.name_template.setText(o.name_template)
        self.format.set_value(o.format)
        self.mirrorx.set_value(o.mirrorx)
        self.cleanup.setChecked(o.cleanup_intermediate)
        self.write_ssf.setChecked(o.write_ssf)
        self.open_result.setChecked(o.open_result)
        self.setmem.setValue(o.setmem_ratio)
        self.setcpu.setValue(o.setcpu)

    def store(self, s: Settings) -> None:
        o = s.output
        o.name_template = self.name_template.text().strip() or "result_{target}{filter_suffix}"
        o.format = self.format.value()
        o.mirrorx = self.mirrorx.value()
        o.cleanup_intermediate = self.cleanup.isChecked()
        o.write_ssf = self.write_ssf.isChecked()
        o.open_result = self.open_result.isChecked()
        o.setmem_ratio = self.setmem.value()
        o.setcpu = self.setcpu.value()
