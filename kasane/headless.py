"""
ヘッドレス実行（GUI なし）

  pyscript Kasane.py --project <project.json>

GUI で保存したプロジェクト JSON（または tools/make_test_project.py で作ったもの）を
そのまま実行する。統合テストとバッチ処理の両方に使う。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import grouping
from .model import Project
from .pipeline import analyze, build_plan, Runner, RunContext, Cancelled, PipelineError, AnalyzeError
from .staging import WorkDirs, new_work_root
from .util.log import Logger, Level


def prepare_work(project: Project) -> WorkDirs:
    """作業ディレクトリを決めて作成する。project.work_root は「親」として扱い、その下に日時付きフォルダを作る"""
    base = project.effective_work_root() or Path.cwd()
    root = new_work_root(base)
    work = WorkDirs(root)
    work.create()
    return work


def run_project(project: Project, siril, log_sink=None, is_cancelled=lambda: False, on_progress=None,
                library_dir: Optional[Path] = None) -> WorkDirs:
    """Project を実行して WorkDirs を返す。例外は呼び出し側で扱う"""
    grouping.build_groups(project, library_dir)
    issues = analyze(project, project.effective_work_root())
    work = prepare_work(project)
    logger = Logger(sink=log_sink, siril=siril, file=work.log_path)
    try:
        for i in issues:
            logger.log(f"{i.icon} {i.text}", {"error": Level.ERROR, "warn": Level.WARN, "info": Level.INFO}[i.level])
        if any(i.level == "error" for i in issues):
            raise AnalyzeError(issues)
        plan = build_plan(project, work, library_dir)
        for line in plan.summary:
            logger.warn(line)
        project.save(work.project_path)
        if project.settings.output.write_ssf:
            work.ssf_path.write_text(plan.to_ssf(f"作業フォルダ: {work.root}"), encoding="utf-8")
        logger.info(f"作業フォルダ: {work.root}")
        logger.info(f"ステップ数: {len(plan.steps)}")
        ctx = RunContext(siril=siril, work=work, logger=logger, project=project)
        Runner(ctx, is_cancelled=is_cancelled, on_progress=on_progress).run(plan)
        return work
    finally:
        logger.close()


def main_headless(project_path: Path, siril) -> int:
    from .library import resolve_library_dir

    project = Project.load(project_path)
    try:
        config_dir = Path(siril.get_siril_configdir())
    except Exception:
        config_dir = None
    library_dir = resolve_library_dir(project.settings.library.path, config_dir)

    def sink(text: str, level: Level) -> None:
        print(text, flush=True)

    try:
        work = run_project(project, siril, log_sink=sink, library_dir=library_dir)
    except Cancelled:
        print("中止されました")
        return 2
    except (PipelineError, AnalyzeError) as e:
        print(f"エラー: {e}")
        return 1
    print(f"完了: {work.output}")
    return 0
