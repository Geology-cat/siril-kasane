"""
Project + Settings → Siril コマンド列（Plan）

Siril には接続しない純粋なロジック。作業ディレクトリ構造は staging.WorkDirs に従う。
パスの扱い:
  - cd は絶対パスをダブルクォートで囲んで渡す（空白・日本語対応）
  - それ以外（-out= / -dark= / -flat= など）は作業ディレクトリ内の相対パスのみを使う
    （自前で付けた名前なので空白を含まない）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import SIRIL_MIN_VERSION
from ..model import FrameInfo, FrameKind, GroupKey, LightGroup, MasterSource, Project, Settings
from ..model.project import SEQ_BASENAME
from ..report import build_report
from ..staging import WorkDirs, stage_frames, stage_master, cleanup_intermediate
from .steps import Plan, Step


class PlanError(Exception):
    pass


@dataclass
class MasterJob:
    """作成または指定するマスター 1 つ"""

    kind: FrameKind
    master_id: str  # 例 dark_01
    source: MasterSource
    used_by: list[str] = field(default_factory=list)

    @property
    def rel_from_process(self) -> str:
        """process/<x>/ から見た masters/<id> の相対パス（拡張子なし）"""
        return f"../../masters/{self.master_id}"


def _quote(path: Path) -> str:
    return f'"{path}"'


def _frames_key(frames: list[FrameInfo]) -> tuple[str, ...]:
    return tuple(sorted(str(f.path) for f in frames))


class Planner:
    def __init__(self, project: Project, work: WorkDirs, library_dir: Optional[Path] = None):
        self.project = project
        self.work = work
        self.library_dir = library_dir
        self.settings: Settings = project.settings
        self.plan = Plan()
        self.masters: dict[tuple, MasterJob] = {}
        self._counter: dict[FrameKind, int] = {}
        self._bias_flat_needed = False
        self._output_names: dict[str, str] = {}
        self._set_frames: dict[str, list[FrameInfo]] = {}  # 出力名 → 含まれる Light（保存名のサフィックス用）

    # ---- マスターの登録 -----------------------------------------------------

    def _register_master(self, kind: FrameKind, source: MasterSource, group_id: str) -> Optional[MasterJob]:
        """同じ素材のマスターは 1 回だけ作る"""
        if source.mode == "frames":
            if not source.frames:
                return None
            key = (kind, "frames", _frames_key(source.frames))
        elif source.mode == "master_file":
            if source.master_path is None:
                return None
            key = (kind, "file", str(source.master_path))
        else:
            return None
        job = self.masters.get(key)
        if job is None:
            n = self._counter.get(kind, 0) + 1
            self._counter[kind] = n
            job = MasterJob(kind=kind, master_id=f"{kind.value}_{n:02d}", source=source)
            self.masters[key] = job
        job.used_by.append(group_id)
        return job

    # ---- Bias 引数 -------------------------------------------------------------

    def _bias_arg(self, source: MasterSource, job: Optional[MasterJob]) -> Optional[str]:
        if source.mode == "constant" and source.constant is not None:
            return f'-bias="={source.constant:g}"'
        if source.mode == "offset_keyword":
            return '-bias="=64*$OFFSET"'
        if job is not None:
            return f"-bias={job.rel_from_process}"
        return None

    # ---- 全体 ------------------------------------------------------------------

    def build(self) -> Plan:
        p = self.project
        s = self.settings
        if not p.groups:
            raise PlanError("Light がありません")
        if p.sensor not in ("osc", "mono", "rgb"):
            raise PlanError("センサー種別（OSC / Mono）を判定できません。手動で指定してください")
        nonlinear = p.is_nonlinear
        if nonlinear:
            self.plan.summary.append("非線形画像モード: キャリブレーション（Dark / Flat / Bias）は行いません")
            if s.drizzle.enabled:
                self.plan.summary.append("非線形画像モード: Drizzle は使えないため無効にします")
            r = s.registration
            if r.method == "global" and any(f.enabled for f in (r.filter_wfwhm, r.filter_round, r.filter_fwhm, r.filter_quality)):
                self.plan.summary.append("非線形画像モード: ストレッチ済みの星像では FWHM / 真円度が計算できないことがあるため、"
                                         "wFWHM / 真円度 / FWHM / 品質フィルタは無効にします（星数・背景フィルタは有効）")

        # 1) グループごとの依存マスターを集める
        group_jobs: dict[str, dict[str, Optional[MasterJob]]] = {}
        for g in p.groups:
            jobs: dict[str, Optional[MasterJob]] = {"dark": None, "flat": None, "bias": None, "darkflat": None}
            if nonlinear:
                group_jobs[g.group_id] = jobs
                continue
            if s.calibration.use_dark:
                jobs["dark"] = self._register_master(FrameKind.DARK, g.dark, g.group_id)
            if s.calibration.use_flat:
                jobs["flat"] = self._register_master(FrameKind.FLAT, g.flat, g.group_id)
                if s.calibration.flat_calib_mode == "darkflat":
                    jobs["darkflat"] = self._register_master(FrameKind.DARKFLAT, g.darkflat, g.group_id)
            need_bias = s.calibration.use_bias_for_light or (
                s.calibration.use_flat and s.calibration.flat_calib_mode == "bias"
            )
            if need_bias:
                jobs["bias"] = self._register_master(FrameKind.BIAS, g.bias, g.group_id)
            group_jobs[g.group_id] = jobs

        # 2) 準備
        self._add_setup()

        # 3) マスター作成（bias → darkflat → dark → flat の順。flat は bias / darkflat に依存）
        order = [FrameKind.BIAS, FrameKind.DARKFLAT, FrameKind.DARK, FrameKind.FLAT]
        for kind in order:
            for job in [j for j in self.masters.values() if j.kind == kind]:
                self._add_master(job, group_jobs)

        # 4) Light グループ: キャリブレーションはグループ（セッション）ごと、スタックは同じキーをまとめて
        sets = self._stack_sets()
        names = self._output_names_for_sets(sets)
        for i, (gs, out_name) in enumerate(zip(sets, names), start=1):
            seqs = {self._add_group_calibration(g, group_jobs[g.group_id]) for g in gs}
            seq = "pp_light" if "pp_light" in seqs else "light"
            if len(seqs) > 1:
                # 一部のセッションだけキャリブレーションできた場合、merge できないので pp_ 側に揃える必要がある
                self.plan.summary.append(
                    f"{out_name}: セッションによってキャリブレーションの有無が異なります（merge に失敗する可能性）"
                )
            flat_job = next((group_jobs[g.group_id]["flat"] for g in gs if group_jobs[g.group_id]["flat"]), None)
            set_dir = self.work.process_dir(f"s{i:02d}") if len(gs) > 1 else self.work.process_dir(gs[0].group_id)
            self._set_frames[out_name] = [f for g in gs for f in g.frames]
            self._add_stack_set(gs, seq, flat_job, set_dir, out_name)

        # 5) 仕上げ
        self._add_finish(names)
        return self.plan

    # ---- 準備 -------------------------------------------------------------------

    def _add_setup(self) -> None:
        s = self.settings
        ph = "準備"
        self.plan.steps.append(Step.cmd("バージョン確認", "requires", SIRIL_MIN_VERSION, weight=0.1, phase=ph))
        self.plan.steps.append(Step.cmd("拡張子を .fit に設定", "setext", "fit", weight=0.1, phase=ph))
        self.plan.steps.append(
            Step.cmd("ビット深度", "set32bits" if s.stacking.bits32 else "set16bits", weight=0.1, phase=ph)
        )
        if s.output.setmem_ratio > 0:
            self.plan.steps.append(Step.cmd("メモリ比率", "setmem", f"{s.output.setmem_ratio:g}", weight=0.1, phase=ph))
        if s.output.setcpu > 0:
            self.plan.steps.append(Step.cmd("スレッド数", "setcpu", str(s.output.setcpu), weight=0.1, phase=ph))
        self.plan.steps.append(Step.cmd("開いている画像を閉じる", "close", weight=0.1, phase=ph))

    # ---- マスター --------------------------------------------------------------

    def _rej_args(self, kind: FrameKind) -> list[str]:
        c = self.settings.calibration
        if c.master_rej_type == "n":
            return ["rej", "n"]
        return ["rej", c.master_rej_type, f"{c.master_sigma_low:g}", f"{c.master_sigma_high:g}"]

    def _add_master(self, job: MasterJob, group_jobs: dict[str, dict[str, Optional[MasterJob]]]) -> None:
        kind = job.kind
        ph = f"マスター作成: {job.master_id}"
        work = self.work
        if job.source.mode == "master_file":
            path = job.source.master_path

            def _stage(ctx, _p=path, _id=job.master_id):
                dst = stage_master(_p, ctx.work.masters, _id)
                ctx.logger.info(f"既存マスターを使用: {_p} → {dst.name}")

            self.plan.steps.append(Step.py(f"既存マスターを配置 ({kind.label})", _stage, weight=0.2, phase=ph))
            return

        frames = job.source.frames
        n = len(frames)
        in_dir = work.input_dir(kind, job.master_id)
        proc_dir = work.process_dir(f"m_{job.master_id}")
        base = SEQ_BASENAME[kind]
        raw = any(f.source == "raw" for f in frames)

        def _stage(ctx, _frames=frames, _dir=in_dir, _proc=proc_dir, _label=kind.label):
            _proc.mkdir(parents=True, exist_ok=True)
            r = stage_frames(_frames, _dir, log=ctx.logger.warn)
            ctx.logger.info(f"{_label} {len(_frames)} 枚を配置: {r.describe()}")

        self.plan.steps.append(Step.py(f"{kind.label} {n} 枚を配置", _stage, weight=0.2 * n, phase=ph))
        self.plan.steps.append(Step.cmd("入力フォルダへ", "cd", _quote(in_dir), weight=0.1, phase=ph))
        self.plan.steps.append(
            Step.cmd(
                f"{kind.label} を FITS シーケンスに変換",
                "convert", base, f"-out=../../../process/m_{job.master_id}",
                weight=(3.0 if raw else 0.5) * n, phase=ph,
            )
        )
        self.plan.steps.append(Step.cmd("処理フォルダへ", "cd", _quote(proc_dir), weight=0.1, phase=ph))

        stack_seq = base
        norm = "-nonorm"
        if kind == FrameKind.FLAT:
            norm = "-norm=mul"
            c = self.settings.calibration
            calib_args: list[str] = []
            if c.flat_calib_mode == "bias":
                # このフラットを使うグループの bias を使う（最初のグループ）
                bias_job = None
                bias_src = None
                for gid in job.used_by:
                    bias_job = group_jobs[gid]["bias"]
                    bias_src = next(g.bias for g in self.project.groups if g.group_id == gid)
                    if bias_job is not None or bias_src.mode in ("constant", "offset_keyword"):
                        break
                arg = self._bias_arg(bias_src, bias_job) if bias_src else None
                if arg:
                    calib_args.append(arg)
                else:
                    self.plan.summary.append(f"{job.master_id}: Bias が無いためキャリブレーションせずにスタックします")
            elif c.flat_calib_mode == "darkflat":
                df_job = None
                for gid in job.used_by:
                    df_job = group_jobs[gid]["darkflat"]
                    if df_job is not None:
                        break
                if df_job is not None:
                    calib_args.append(f"-dark={df_job.rel_from_process}")
                else:
                    self.plan.summary.append(f"{job.master_id}: Dark Flat が無いためキャリブレーションせずにスタックします")
            if calib_args:
                self.plan.steps.append(
                    Step.cmd("Flat をキャリブレーション", "calibrate", base, *calib_args, weight=1.0 * n, phase=ph)
                )
                stack_seq = f"pp_{base}"

        self.plan.steps.append(
            Step.cmd(
                f"{kind.label} をスタック → masters/{job.master_id}",
                "stack", stack_seq, *self._rej_args(kind), norm, f"-out=../../masters/{job.master_id}",
                weight=1.5 * n, phase=ph,
            )
        )
        if self.settings.library.save_masters and self.library_dir is not None:
            def _save(ctx, _kind=kind, _id=job.master_id, _frames=frames, _lib=self.library_dir):
                from ..library import MasterLibrary

                src = ctx.work.masters / f"{_id}.fit"
                if not src.exists():
                    ctx.logger.warn(f"ライブラリ保存: {src.name} が見つかりません")
                    return
                entry = MasterLibrary(_lib).add(_kind, src, _frames[0], len(_frames))
                ctx.logger.ok(f"ライブラリに保存: {entry.fit_path.name}")

            self.plan.steps.append(Step.py(f"{job.master_id} をライブラリへ保存", _save, weight=0.3, phase=ph))

    # ---- Light グループ ----------------------------------------------------------

    def _stack_sets(self) -> list[list[LightGroup]]:
        """同じキー（露出 / Gain / Filter / Bin / サイズ）のグループをまとめる。セッション違いはここで 1 本になる"""
        sets: dict[GroupKey, list[LightGroup]] = {}
        for g in self.project.groups:
            sets.setdefault(g.key, []).append(g)
        return list(sets.values())

    def _output_names_for_sets(self, sets: list[list[LightGroup]]) -> list[str]:
        p = self.project
        tpl = self.settings.output.name_template or "result_{target}{filter_suffix}"
        target = p.effective_target_name()
        names: list[str] = []
        for i, gs in enumerate(sets, start=1):
            key = gs[0].key
            filt = key.filter or ""
            name = tpl.format(
                target=target,
                filter=_safe(filt),
                filter_suffix=f"_{_safe(filt)}" if filt else "",
                group=f"s{i:02d}" if len(gs) > 1 else gs[0].group_id,
            )
            names.append(_safe(name) or "result")
        # 衝突したらセット番号を付ける
        counts: dict[str, int] = {}
        for n in names:
            counts[n] = counts.get(n, 0) + 1
        for i, n in enumerate(names):
            if counts[n] > 1:
                suffix = sets[i][0].group_id if len(sets[i]) == 1 else f"s{i + 1:02d}"
                names[i] = f"{n}_{suffix}"
        return names

    def _add_group_calibration(self, g: LightGroup, jobs: dict[str, Optional[MasterJob]]) -> str:
        """Light グループの配置 → 変換 → キャリブレーション。処理後のシーケンス名（pp_light / light）を返す"""
        s = self.settings
        p = self.project
        work = self.work
        n = len(g.frames)
        raw = g.source == "raw"
        osc = p.is_osc
        ph = f"Light {g.group_id}: {g.label}"
        in_dir = work.input_dir(FrameKind.LIGHT, g.group_id)
        proc_dir = work.process_dir(g.group_id)

        def _stage(ctx, _frames=g.frames, _dir=in_dir, _proc=proc_dir):
            _proc.mkdir(parents=True, exist_ok=True)
            r = stage_frames(_frames, _dir, log=ctx.logger.warn)
            ctx.logger.info(f"Light {len(_frames)} 枚を配置: {r.describe()}")

        self.plan.steps.append(Step.py(f"Light {n} 枚を配置", _stage, weight=0.2 * n, phase=ph))
        self.plan.steps.append(Step.cmd("入力フォルダへ", "cd", _quote(in_dir), weight=0.1, phase=ph))
        self.plan.steps.append(
            Step.cmd("Light を FITS シーケンスに変換", "convert", "light", f"-out=../../../process/{g.group_id}",
                     weight=(3.0 if raw else 0.5) * n, phase=ph)
        )
        self.plan.steps.append(Step.cmd("処理フォルダへ", "cd", _quote(proc_dir), weight=0.1, phase=ph))

        c = s.calibration
        args: list[str] = []
        if jobs["dark"] is not None:
            args.append(f"-dark={jobs['dark'].rel_from_process}")
        if jobs["flat"] is not None:
            args.append(f"-flat={jobs['flat'].rel_from_process}")
        if c.use_bias_for_light:
            arg = self._bias_arg(g.bias, jobs["bias"])
            if arg:
                args.append(arg)
        cosmetic = c.cosmetic_enabled and jobs["dark"] is not None
        if cosmetic:
            args.append(f"-cc=dark {c.cc_sigma_low:g} {c.cc_sigma_high:g}")
        if osc:
            if cosmetic:
                args.append("-cfa")  # CFA 画像の Cosmetic Correction 用
            if c.equalize_cfa and jobs["flat"] is not None:
                args.append("-equalize_cfa")
            if not s.drizzle.enabled:
                args.append("-debayer")
        if c.dark_opt == "on" and jobs["dark"] is not None:
            args.append("-opt")
        elif c.dark_opt == "exp" and jobs["dark"] is not None:
            args.append("-opt=exp")
        if not args:
            self.plan.summary.append(f"{g.group_id}: キャリブレーション用マスターが無いため変換のみ行います")
        if args or osc:
            self.plan.steps.append(Step.cmd("Light をキャリブレーション", "calibrate", "light", *args, weight=1.0 * n, phase=ph))
            return "pp_light"
        return "light"

    def _add_stack_set(self, groups: list[LightGroup], seq: str, flat_job: Optional[MasterJob],
                       set_dir: Path, out_name: str) -> None:
        """（必要なら merge →）レジストレーション → 品質フィルタ → スタック"""
        s = self.settings
        p = self.project
        work = self.work
        osc = p.is_osc
        n = sum(len(g.frames) for g in groups)
        if len(groups) > 1:
            ph = f"スタック {set_dir.name}: {groups[0].key.label(groups[0].source)}（{len(groups)} セッション）"
            self.plan.steps.append(Step.py(f"{set_dir.name} フォルダを作成", lambda ctx, _d=set_dir: _d.mkdir(parents=True, exist_ok=True),
                                           weight=0.1, phase=ph))
            self.plan.steps.append(Step.cmd("結合フォルダへ", "cd", _quote(set_dir), weight=0.1, phase=ph))
            self.plan.steps.append(
                Step.cmd(f"{len(groups)} セッションのシーケンスを結合", "merge",
                         *[f"../{g.group_id}/{seq}" for g in groups], seq, weight=0.5 * n, phase=ph)
            )
        else:
            ph = f"Light {groups[0].group_id}: {groups[0].label}"

        r = s.registration
        nonlinear = p.is_nonlinear
        if r.method == "none":
            # 位置合わせしない: 変換後（キャリブ後）のシーケンスをそのままスタックする
            self.plan.summary.append(f"{out_name}: 位置合わせを行わずにスタックします")
            self._add_stack_cmd(seq, set_dir, out_name, n, ph, osc, filter_args=[], registered=False)
            return
        reg_args: list[str] = []
        if r.transf != "homography":
            reg_args.append(f"-transf={r.transf}")
        if r.minpairs > 0:
            reg_args.append(f"-minpairs={r.minpairs}")
        if r.maxstars > 0:
            reg_args.append(f"-maxstars={r.maxstars}")
        apply_args: list[str] = []
        if r.interp != "default":
            apply_args.append(f"-interp={r.interp}")
        if not r.clamping:
            apply_args.append("-noclamp")
        if r.framing != "current":
            apply_args.append(f"-framing={r.framing}")
        d = s.drizzle
        if d.enabled and not nonlinear:
            apply_args.append("-drizzle")
            if d.scale != 1.0:
                apply_args.append(f"-scale={d.scale:g}")
            apply_args.append(f"-pixfrac={d.pixfrac:g}")
            if d.kernel != "square":
                apply_args.append(f"-kernel={d.kernel}")
            if d.use_flat and flat_job is not None:
                apply_args.append(f"-flat={flat_job.rel_from_process}")
        psf_filters = () if nonlinear else (
            r.filter_fwhm.to_arg("fwhm"),
            r.filter_wfwhm.to_arg("wfwhm"),
            r.filter_round.to_arg("round"),
            r.filter_quality.to_arg("quality"),
        )
        filter_args = [
            a for a in (
                *psf_filters,
                r.filter_bkg.to_arg("bkg"),
                r.filter_nbstars.to_arg("nbstars"),
            ) if a
        ]
        drz_w = 3.0 if (d.enabled and not nonlinear) else 2.0
        if r.two_pass:
            self.plan.steps.append(Step.cmd("レジストレーション（2-pass、変換行列のみ）", "register", seq, "-2pass", *reg_args,
                                            weight=2.0 * n, phase=ph))
            self.plan.steps.append(Step.cmd("レジストレーション適用（品質フィルタ）", "seqapplyreg", seq, *apply_args, *filter_args,
                                            weight=drz_w * n, phase=ph))
            stack_filter_args: list[str] = ["-filter-included"]
        else:
            self.plan.steps.append(Step.cmd("レジストレーション", "register", seq, *reg_args, *apply_args,
                                            weight=(2.0 + drz_w) * n, phase=ph))
            stack_filter_args = [*filter_args, "-filter-included"]
        seq = f"r_{seq}"
        self._add_stack_cmd(seq, set_dir, out_name, n, ph, osc, stack_filter_args, registered=True, groups=groups)

    def _add_stack_cmd(self, seq: str, set_dir: Path, out_name: str, n: int, ph: str, osc: bool,
                       filter_args: list[str], registered: bool, groups: Optional[list[LightGroup]] = None) -> None:
        """stack コマンドと（位置合わせ済みなら）品質レポートのステップを追加する"""
        s = self.settings
        work = self.work
        st = s.stacking
        stack_args: list[str] = []
        method = st.method if st.method in ("rej", "med", "sum", "max", "min") else "rej"
        if method == "rej":
            if st.rej_type == "n":
                stack_args += ["rej", "n"]
            else:
                stack_args += ["rej", st.rej_type, f"{st.sigma_low:g}", f"{st.sigma_high:g}"]
            if st.rejmap:
                stack_args.append("-rejmap")
        else:
            stack_args.append(method)
        if method in ("rej", "med"):
            stack_args.append("-nonorm" if st.norm == "none" else f"-norm={st.norm}")
            if st.fastnorm and st.norm != "none":
                stack_args.append("-fastnorm")
            if st.rgb_equal and osc:
                stack_args.append("-rgb_equal")
        if method == "rej":
            if st.weight != "none" and registered:
                stack_args.append(f"-weight={st.weight}")
            if st.feather > 0:
                stack_args.append(f"-feather={st.feather}")
        if st.output_norm:
            stack_args.append("-output_norm")
        if st.bits32:
            stack_args.append("-32b")
        stack_args += filter_args
        stack_args.append(f"-out=../../output/{out_name}")
        self.plan.steps.append(Step.cmd(f"スタック → output/{out_name}", "stack", seq, *stack_args, weight=1.5 * n, phase=ph))
        self.plan.outputs.append(work.output / out_name)
        if not registered or groups is None:
            return

        # 品質レポート（登録データは入力側の .seq、採否は r_ 側の .seq）
        in_seq = seq[2:]  # "r_" を外す
        all_frames = [f for g in groups for f in g.frames]

        def _report(ctx, _dir=set_dir, _in=in_seq, _out=seq, _frames=all_frames, _title=out_name):
            reg_seq = _dir / f"{_in}_.seq"
            out_seq = _dir / f"{_out}_.seq"
            if not reg_seq.exists() and not out_seq.exists():
                ctx.logger.warn(f"品質レポート: {reg_seq.name} が見つかりません")
                return
            rep = build_report(_title, reg_seq if reg_seq.exists() else out_seq, out_seq, _frames,
                               ctx.work.output / f"quality_{_title}.csv")
            for line in rep.summary_lines():
                (ctx.logger.warn if "除外:" in line else ctx.logger.info)(line)

        self.plan.steps.append(Step.py(f"品質レポート → output/quality_{out_name}.csv", _report, weight=0.2, phase=ph))

    # ---- 仕上げ -------------------------------------------------------------------

    def _add_finish(self, names: list[str]) -> None:
        s = self.settings
        p = self.project
        work = self.work
        ph = "仕上げ"
        mirror = s.output.mirrorx == "on" or (s.output.mirrorx == "auto" and p.is_raw)
        self.plan.steps.append(Step.cmd("出力フォルダへ", "cd", _quote(work.output), weight=0.1, phase=ph))
        fmt = s.output.format if s.output.format in ("fit", "tif", "both") else "fit"
        for name in names:
            frames = self._set_frames.get(name, [])
            # 露出が全フレームで分かるときだけ Siril の $LIVETIME トークン（積算秒）を使う。
            # EXIF の無い書き出し画像などでは展開されない（"LIVETIMEs" のまま残る）ので枚数を付ける
            if frames and all(f.exposure for f in frames):
                saved = f"{name}_$LIVETIME:%d$s"
                desc = "積算時間付きの名前で保存"
            else:
                saved = f"{name}_{len(frames)}frames"
                desc = "枚数付きの名前で保存"
            self.plan.steps.append(Step.cmd(f"{name} を読込", "load", name, weight=0.3, phase=ph))
            if mirror:
                self.plan.steps.append(Step.cmd("上下反転（DSLR の向き補正）", "mirrorx", "-bottomup", weight=0.3, phase=ph))
            if fmt in ("fit", "both"):
                self.plan.steps.append(Step.cmd(f"{desc}（FITS）", "save", saved, weight=0.3, phase=ph))
            if fmt in ("tif", "both"):
                self.plan.steps.append(Step.cmd(f"{desc}（16bit TIFF）", "savetif", saved, weight=0.3, phase=ph))

            def _remove_plain(ctx, _name=name):
                plain = ctx.work.output / f"{_name}.fit"
                if plain.exists():
                    plain.unlink()

            self.plan.steps.append(Step.py(f"{name}.fit（保存前の一時ファイル）を削除", _remove_plain, weight=0.1, phase=ph))
        self.plan.steps.append(Step.cmd("閉じる", "close", weight=0.1, phase=ph))

        if s.output.cleanup_intermediate:
            def _cleanup(ctx):
                cleanup_intermediate(ctx.work, keep_masters=True, log=ctx.logger.info)

            self.plan.steps.append(Step.py("中間ファイルを削除", _cleanup, weight=0.5, phase=ph))

        if s.output.open_result and names:
            first = names[0]

            def _open(ctx, _name=first):
                cands = sorted(ctx.work.output.glob(f"{_name}_*.fit")) or sorted(ctx.work.output.glob(f"{_name}_*.tif"))
                if cands:
                    ctx.siril.cmd("load", _quote(cands[-1]))
                    ctx.logger.ok(f"結果を開きました: {cands[-1].name}")

            self.plan.steps.append(Step.py("結果を Siril で開く", _open, weight=0.3, phase=ph))


def _safe(name: str) -> str:
    bad = '<>:"/\\|?* '
    return "".join("_" if c in bad else c for c in name)


def build_plan(project: Project, work: WorkDirs, library_dir: Optional[Path] = None) -> Plan:
    return Planner(project, work, library_dir).build()
