"""
Plan を Siril に対して順番に実行する

- Siril の処理スレッドは 1 本なので必ず直列
- 中止はステップ境界でのみ判定する（実行中の Siril コマンドは止められない）
- 実行したコマンドは commands.ssf に追記する
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..model import Project
from ..staging import WorkDirs
from ..util.log import Logger
from .steps import Plan, Step


class Cancelled(Exception):
    pass


class PipelineError(Exception):
    def __init__(self, step: Step, cause: Exception):
        super().__init__(f"{step.description} に失敗: {cause}")
        self.step = step
        self.cause = cause


@dataclass
class RunContext:
    siril: object  # sirilpy.SirilInterface（または dry-run 用のダミー）
    work: WorkDirs
    logger: Logger
    project: Project


class Runner:
    def __init__(
        self,
        ctx: RunContext,
        is_cancelled: Callable[[], bool] = lambda: False,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ):
        self.ctx = ctx
        self.is_cancelled = is_cancelled
        self.on_progress = on_progress or (lambda *_: None)

    def run(self, plan: Plan) -> None:
        ctx = self.ctx
        total = plan.total_weight
        done = 0.0
        started = time.time()
        ssf_path = ctx.work.ssf_path
        ssf_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ssf_path, "a", encoding="utf-8") as ssf:
            ssf.write(f"# ---- 実行開始 {time.strftime('%Y-%m-%d %H:%M:%S')} ----\n")
            for i, step in enumerate(plan.steps):
                if self.is_cancelled():
                    ctx.logger.warn("ユーザーが中止しました")
                    ssf.write("# 中止\n")
                    raise Cancelled()
                self.on_progress(done / total, f"[{step.phase}] {step.description}")
                t0 = time.time()
                try:
                    if step.kind == "cmd":
                        ctx.logger.cmd(step.command_text)
                        ctx.siril.cmd(*step.args)
                        ssf.write(step.command_text + "\n")
                    else:
                        ctx.logger.info(f"[python] {step.description}")
                        step.func(ctx)
                        ssf.write(step.command_text + "\n")
                    ssf.flush()
                except Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    ctx.logger.error(f"失敗: {step.description}\n  {step.command_text}\n  {e}")
                    ssf.write(f"# ERROR: {e}\n")
                    raise PipelineError(step, e) from e
                dt = time.time() - t0
                if dt > 2:
                    ctx.logger.info(f"  完了 ({dt:.0f} 秒)")
                done += step.weight
                try:
                    ctx.siril.update_progress(f"Kasane {i + 1}/{len(plan.steps)}", done / total)
                except Exception:
                    pass
            elapsed = time.time() - started
            ssf.write(f"# ---- 完了 ({elapsed:.0f} 秒) ----\n")
        self.on_progress(1.0, "完了")
        try:
            ctx.siril.reset_progress()
        except Exception:
            pass
        ctx.logger.ok(f"すべて完了しました（{_fmt_elapsed(elapsed)}）")


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h} 時間 {m} 分 {s} 秒"
    if m:
        return f"{m} 分 {s} 秒"
    return f"{s} 秒"


class DryRunSiril:
    """Siril に接続せずにコマンドをログに流すだけのダミー（GUI 開発・テスト用）"""

    def __init__(self, log: Optional[Callable[[str], None]] = None, delay: float = 0.0):
        self.commands: list[list[str]] = []
        self._log = log or (lambda s: None)
        self.delay = delay

    def cmd(self, *args: str) -> None:
        self.commands.append(list(args))
        self._log("(dry-run) " + " ".join(args))
        if self.delay:
            time.sleep(self.delay)

    def log(self, text: str, color=None) -> bool:
        return True

    def update_progress(self, text: str, value: float) -> bool:
        return True

    def reset_progress(self) -> bool:
        return True

    def is_cli(self) -> bool:
        return False

    def get_siril_wd(self) -> str:
        return str(Path.home())

    def get_siril_configdir(self) -> str:
        return str(Path.home() / ".kasane_dryrun")
