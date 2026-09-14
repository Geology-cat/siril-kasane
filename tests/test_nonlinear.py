import unittest
from pathlib import Path

from kasane import grouping
from kasane.metadata.reader import is_nonlinear, is_supported
from kasane.model import FrameKind, Project, Settings
from kasane.pipeline import analyze, build_plan
from kasane.staging import WorkDirs
from tests.helpers import frame, frames, osc_cmos_project

WORK = WorkDirs(Path("/work/Kasane_test"))


def cmds(plan) -> list[str]:
    return [s.command_text for s in plan.steps if s.kind == "cmd"]


def image_project(n: int = 6, ext: str = ".jpg") -> Project:
    p = Project()
    p.lights = [
        frame(f"IMG_{i:03d}{ext}", FrameKind.LIGHT, source="image", sensor="rgb", exposure=30.0, gain=800.0,
              temp=None, size=None)
        for i in range(n)
    ]
    p.settings = Settings()
    p.work_root = Path("/work/Kasane_test")
    p.target_name = "Trails"
    return p


class NonlinearTest(unittest.TestCase):
    def test_extension_detection(self):
        for e in (".jpg", ".JPEG", ".png", ".tif", ".TIFF", ".heic", ".avif"):
            self.assertTrue(is_supported(Path("x" + e)))
            self.assertTrue(is_nonlinear(Path("x" + e)))
        self.assertFalse(is_nonlinear(Path("x.fit")))
        self.assertFalse(is_nonlinear(Path("x.cr2")))

    def test_project_flags(self):
        p = image_project()
        self.assertTrue(p.is_nonlinear)
        self.assertEqual(p.sensor, "rgb")
        self.assertFalse(p.is_osc)
        self.assertFalse(p.is_raw)
        # 非線形が過半数ならモード ON。少数の混入は警告
        p.lights += frames("L", FrameKind.LIGHT, 2)
        self.assertTrue(p.is_nonlinear)
        grouping.build_groups(p)
        issues = analyze(p, Path("/tmp/Kasane_x"))
        self.assertTrue(any("非線形画像モード" in i.text for i in issues))
        self.assertTrue(any(i.level == "warn" and "混ざって" in i.text for i in issues))
        self.assertFalse(any(i.level == "error" for i in issues))

    def test_plan_skips_calibration_and_psf_filters(self):
        p = image_project()
        p.dark_pool = frames("D", FrameKind.DARK, 3)  # 投入されていても無視される
        p.settings.drizzle.enabled = True
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        self.assertEqual([x for x in c if x.startswith("calibrate")], [])
        self.assertEqual([x for x in c if x.startswith("stack dark")], [])
        self.assertTrue(any(x.startswith("convert light") for x in c))
        self.assertIn("register light -2pass -minpairs=10", c)
        apply = next(x for x in c if x.startswith("seqapplyreg"))
        self.assertEqual(apply, "seqapplyreg light")  # wFWHM / 真円度フィルタも Drizzle も付かない
        stack = next(x for x in c if x.startswith("stack r_light"))
        self.assertNotIn("-rgb_equal", stack)
        self.assertNotIn("-cfa", " ".join(c))
        self.assertTrue(any("Drizzle は使えない" in m for m in plan.summary))
        self.assertTrue(any("wFWHM / 真円度" in m for m in plan.summary))
        # 星数フィルタは残る
        p.settings.registration.filter_nbstars.enabled = True
        plan = build_plan(p, WORK)
        apply = next(x for x in cmds(plan) if x.startswith("seqapplyreg"))
        self.assertEqual(apply, "seqapplyreg light -filter-nbstars=90%")
        # レポートは登録データがあるので付く
        self.assertTrue(any("品質レポート" in s.description for s in plan.steps))

    def test_registration_none_and_tif_output(self):
        p = image_project()
        p.settings.registration.method = "none"
        p.settings.stacking.method = "max"
        p.settings.output.format = "tif"
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        self.assertEqual([x for x in c if x.startswith("register") or x.startswith("seqapplyreg")], [])
        self.assertIn("stack light max -output_norm -32b -out=../../output/result_Trails", c)
        self.assertFalse(any("品質レポート" in s.description for s in plan.steps))
        # 露出が分かるので LIVETIME トークンを使う
        self.assertIn("savetif result_Trails_$LIVETIME:%d$s", c)
        self.assertNotIn("save result_Trails_$LIVETIME:%d$s", c)
        p.settings.output.format = "both"
        c = cmds(build_plan(p, WORK))
        self.assertIn("savetif result_Trails_$LIVETIME:%d$s", c)
        self.assertIn("save result_Trails_$LIVETIME:%d$s", c)
        # 露出不明（EXIF の無い書き出し画像）なら枚数を付ける
        for f in p.lights:
            f.exposure = None
        grouping.build_groups(p)
        c = cmds(build_plan(p, WORK))
        self.assertIn("savetif result_Trails_6frames", c)

    def test_registration_none_on_linear_data_keeps_calibration(self):
        p = osc_cmos_project()
        p.settings.registration.method = "none"
        grouping.build_groups(p)
        c = cmds(build_plan(p, WORK))
        self.assertTrue(any(x.startswith("calibrate light") for x in c))
        self.assertTrue(any(x.startswith("stack pp_light rej") for x in c))
        self.assertEqual([x for x in c if x.startswith("register")], [])


if __name__ == "__main__":
    unittest.main()
