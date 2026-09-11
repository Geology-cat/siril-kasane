"""
統合テスト用のプロジェクト JSON を作る

  python tools/make_test_project.py <data_dir>... --work <work_parent> --out <project.json> [--drizzle]

data_dir には make_test_data.py の出力（lights/ darks/ flats/ darkflats/）を渡す。複数可（Mono の各フィルター）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kasane import grouping  # noqa: E402
from kasane.metadata.reader import collect_files, read_frames  # noqa: E402
from kasane.model import FrameKind, Project  # noqa: E402
from kasane.pipeline import analyze  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="+", type=Path)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--drizzle", action="store_true")
    ap.add_argument("--no-cleanup", action="store_true")
    args = ap.parse_args()

    p = Project()
    for d in args.data:
        p.lights += read_frames(collect_files([d / "lights"]), FrameKind.LIGHT)
        p.dark_pool += read_frames(collect_files([d / "darks"]), FrameKind.DARK)
        p.flat_pool += read_frames(collect_files([d / "flats"]), FrameKind.FLAT)
        p.darkflat_pool += read_frames(collect_files([d / "darkflats"]), FrameKind.DARKFLAT)
    p.darkflat_mode = "frames"
    p.settings.calibration.flat_calib_mode = "darkflat"
    p.settings.output.cleanup_intermediate = not args.no_cleanup
    p.settings.output.open_result = False
    if args.drizzle:
        p.settings.drizzle.enabled = True
        p.settings.drizzle.scale = 2.0
        p.settings.drizzle.pixfrac = 0.9
    p.work_root = args.work.resolve()
    p.target_name = "Synthetic"
    grouping.build_groups(p)
    for i in analyze(p, p.work_root):
        print(i.icon, i.text)
    for g in p.groups:
        print(g.group_id, g.label, len(g.frames), "| dark:", g.dark.describe(), "| flat:", g.flat.describe(),
              "| darkflat:", g.darkflat.describe())
    p.save(args.out)
    print("saved", args.out)


if __name__ == "__main__":
    main()
