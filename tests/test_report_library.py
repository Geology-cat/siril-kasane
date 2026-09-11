import tempfile
import unittest
from pathlib import Path

from kasane import grouping
from kasane.library import MasterLibrary
from kasane.model import FrameKind
from kasane.pipeline import build_plan
from kasane.report import build_report, parse_seq, read_csv
from kasane.staging import WorkDirs
from tests.helpers import frame, frames, osc_cmos_project

SEQ_IN = """#Siril sequence file.
S 'pp_light_' 1 4 4 5 2 6 0 0 0
L 3
I 1 1
I 2 1
I 3 1
I 4 1
R1 4.1 4.2 0.98 0 0.012 56 H 1 0 0 0 1 0 0 0 1
R1 5.0 6.5 0.90 0 0.013 40 H 1 0 0 0 1 0 0 0 1
R1 4.0 4.0 0.99 0 0.012 57 H 1 0 0 0 1 0 0 0 1
R1 4.3 4.4 0.97 0 0.012 55 H 1 0 0 0 1 0 0 0 1
M1-0 1 1 0 0 0 0 0 0 0 0 0 0 1 0
"""
SEQ_OUT = """S 'r_pp_light_' 1 3 3 5 2 6 0 0 0
L 3
I 1 1
I 3 1
I 4 1
R1 4.1 4.2 0.98 0 0.012 56 H 1 0 0 0 1 0 0 0 1
R1 4.0 4.0 0.99 0 0.012 57 H 1 0 0 0 1 0 0 0 1
R1 4.3 4.4 0.97 0 0.012 55 H 1 0 0 0 1 0 0 0 1
"""


class ReportTest(unittest.TestCase):
    def test_parse_and_build(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "pp_light_.seq").write_text(SEQ_IN)
            (d / "r_pp_light_.seq").write_text(SEQ_OUT)
            seq = parse_seq(d / "pp_light_.seq")
            self.assertEqual(seq.nb_images, 4)
            self.assertEqual(seq.reference, 2)
            self.assertEqual(seq.reg[2].wfwhm, 6.5)
            fs = frames("L", FrameKind.LIGHT, 4)
            rep = build_report("result_M31", d / "pp_light_.seq", d / "r_pp_light_.seq", fs, d / "quality_result_M31.csv")
            self.assertEqual(rep.n_total, 4)
            self.assertEqual(rep.n_included, 3)
            self.assertEqual([r.name for r in rep.excluded()], ["L_001.fit"])
            self.assertTrue(rep.rows[2].reference)
            lines = rep.summary_lines()
            self.assertIn("採用 3 / 4 枚", lines[0])
            self.assertTrue(any("除外: L_001.fit" in l and "6.50" in l for l in lines))
            back = read_csv(d / "quality_result_M31.csv")
            self.assertEqual(back.n_included, 3)
            self.assertEqual(back.rows[1].reg.nb_stars, 40)


class LibraryTest(unittest.TestCase):
    def test_add_list_and_match(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            lib = MasterLibrary(d / "lib")
            master = d / "dark_01.fit"
            master.write_bytes(b"x" * 100)
            tpl = frame("D_000.fit", FrameKind.DARK)
            e = lib.add(FrameKind.DARK, master, tpl, 5)
            self.assertTrue(e.fit_path.exists() and e.json_path.exists())
            self.assertTrue(e.fit_path.name.startswith("dark_180s_G100_-10C_1x1_6248x4176_"))
            self.assertEqual(len(lib.entries(FrameKind.DARK)), 1)
            self.assertEqual(lib.entries(FrameKind.FLAT), [])
            # 2 回目は名前が衝突しないこと
            e2 = lib.add(FrameKind.DARK, master, tpl, 5)
            self.assertNotEqual(e.fit_path, e2.fit_path)

            # グループ化: モード library
            p = osc_cmos_project()
            p.dark_pool = []
            p.dark_mode = "library"
            g = grouping.build_groups(p, d / "lib")[0]
            self.assertEqual(g.dark.mode, "master_file")
            self.assertEqual(g.dark.master_path, e.fit_path)
            self.assertIn("ライブラリ", g.dark.note)
            # フォールバック（frames モードだが投入なし）
            p.dark_mode = "frames"
            g = grouping.build_groups(p, d / "lib")[0]
            self.assertEqual(g.dark.mode, "master_file")
            p.settings.library.auto_fallback = False
            g = grouping.build_groups(p, d / "lib")[0]
            self.assertEqual(g.dark.mode, "none")
            # 投入フレームがあればそちらを優先
            p.dark_pool = frames("D", FrameKind.DARK, 3)
            p.settings.library.auto_fallback = True
            g = grouping.build_groups(p, d / "lib")[0]
            self.assertEqual(g.dark.mode, "frames")
            # planner: ライブラリのマスターは配置のみ、保存ステップは save_masters のときだけ
            p.dark_pool = []
            grouping.build_groups(p, d / "lib")
            plan = build_plan(p, WorkDirs(Path("/work/x")), d / "lib")
            self.assertFalse(any("ライブラリへ保存" in s.description for s in plan.steps))
            self.assertTrue(any("品質レポート" in s.description for s in plan.steps))
            p.settings.library.save_masters = True
            plan = build_plan(p, WorkDirs(Path("/work/x")), d / "lib")
            saves = [s.description for s in plan.steps if "ライブラリへ保存" in s.description]
            self.assertEqual(sorted(saves), sorted(["darkflat_01 をライブラリへ保存", "flat_01 をライブラリへ保存"]))
            lib.remove(e)
            self.assertEqual(len(lib.entries()), 1)


if __name__ == "__main__":
    unittest.main()
