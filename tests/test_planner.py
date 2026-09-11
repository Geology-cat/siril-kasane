import unittest
from pathlib import Path

from kasane import grouping
from kasane.model import FrameKind, Settings
from kasane.pipeline import build_plan, PlanError
from kasane.staging import WorkDirs
from tests.helpers import dslr_project, frames, mono_project, osc_cmos_project

WORK = WorkDirs(Path("/work/Kasane_test"))


def cmds(plan) -> list[str]:
    return [s.command_text for s in plan.steps if s.kind == "cmd"]


def find(plan, prefix: str) -> list[str]:
    return [c for c in cmds(plan) if c.startswith(prefix)]


class PlannerTest(unittest.TestCase):
    def test_osc_cmos_darkflat(self):
        p = osc_cmos_project()
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        # 準備
        self.assertEqual(c[:4], ["requires 1.4.0", "setext fit", "set32bits", "close"])
        # マスター: darkflat → dark → flat の順
        self.assertIn("stack darkflat rej w 3 3 -nonorm -out=../../masters/darkflat_01", c)
        self.assertIn("stack dark rej w 3 3 -nonorm -out=../../masters/dark_01", c)
        self.assertIn("calibrate flat -dark=../../masters/darkflat_01", c)
        self.assertIn("stack pp_flat rej w 3 3 -norm=mul -out=../../masters/flat_01", c)
        self.assertLess(c.index("stack darkflat rej w 3 3 -nonorm -out=../../masters/darkflat_01"),
                        c.index("calibrate flat -dark=../../masters/darkflat_01"))
        # Light（公式 OSC_Preprocessing.ssf 相当）
        self.assertIn(
            "calibrate light -dark=../../masters/dark_01 -flat=../../masters/flat_01 -cc=dark 0 3 -cfa -equalize_cfa -debayer",
            c,
        )
        self.assertIn("register pp_light -2pass -minpairs=10", c)
        self.assertIn("seqapplyreg pp_light -filter-wfwhm=3k -filter-round=3k", c)
        self.assertIn(
            "stack r_pp_light rej w 3 3 -norm=addscale -rgb_equal -output_norm -32b -filter-included -out=../../output/result_M31",
            c,
        )
        # 仕上げ: FITS 入力なので mirrorx なし
        self.assertNotIn("mirrorx -bottomup", c)
        self.assertIn("save result_M31_$LIVETIME:%d$s", c)
        self.assertEqual(plan.outputs, [WORK.output / "result_M31"])

    def test_dslr_constant_bias_and_mirrorx(self):
        p = dslr_project()
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        self.assertIn('calibrate flat -bias="=2048"', c)
        self.assertIn("mirrorx -bottomup", c)
        # Light には Bias を引かない（Dark に含まれる）
        light = find(plan, "calibrate light")[0]
        self.assertNotIn("-bias", light)
        self.assertIn("-debayer", light)
        # RAW の convert は重い
        conv = next(s for s in plan.steps if s.kind == "cmd" and s.args[:2] == ["convert", "light"])
        self.assertGreater(conv.weight, 10)

    def test_bayer_drizzle(self):
        p = osc_cmos_project()
        p.settings.drizzle.enabled = True
        p.settings.drizzle.scale = 2.0
        p.settings.drizzle.pixfrac = 0.9
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        light = find(plan, "calibrate light")[0]
        self.assertNotIn("-debayer", light)  # Bayer Drizzle は CFA のまま
        apply = find(plan, "seqapplyreg")[0]
        self.assertIn("-drizzle -scale=2 -pixfrac=0.9 -flat=../../masters/flat_01", apply)

    def test_mono_two_filters(self):
        p = mono_project()
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        lights = find(plan, "calibrate light")
        self.assertEqual(len(lights), 2)
        for l in lights:
            self.assertNotIn("-cfa", l)
            self.assertNotIn("-debayer", l)
            self.assertNotIn("-equalize_cfa", l)
        stacks = find(plan, "stack r_pp_light")
        self.assertEqual(len(stacks), 2)
        self.assertNotIn("-rgb_equal", stacks[0])
        self.assertTrue(stacks[0].endswith("-out=../../output/result_NGC7000_Ha"))
        self.assertTrue(stacks[1].endswith("-out=../../output/result_NGC7000_OIII"))
        # Flat は 2 つ、Dark は 1 つ、Dark Flat は 2 つ
        self.assertEqual(len(find(plan, "stack pp_flat")), 2)
        self.assertEqual(len(find(plan, "stack dark ")), 1)
        self.assertEqual(len(find(plan, "stack darkflat")), 2)
        self.assertIn("calibrate flat -dark=../../masters/darkflat_01", c)
        self.assertIn("calibrate flat -dark=../../masters/darkflat_02", c)

    def test_master_file_is_staged_not_built(self):
        p = osc_cmos_project()
        p.dark_mode = "master_file"
        p.dark_master_path = Path("/lib/master_dark.fit")
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        self.assertEqual(find(plan, "stack dark "), [])
        self.assertTrue(any(s.kind == "py" and "既存マスター" in s.description for s in plan.steps))
        self.assertIn("-dark=../../masters/dark_01", find(plan, "calibrate light")[0])

    def test_offset_keyword_bias_and_no_two_pass(self):
        p = osc_cmos_project(with_darkflat=False)
        p.bias_mode = "offset_keyword"
        p.settings.calibration.flat_calib_mode = "bias"
        p.settings.registration.two_pass = False
        p.settings.registration.interp = "cubic"
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        self.assertIn('calibrate flat -bias="=64*$OFFSET"', c)
        self.assertEqual(find(plan, "seqapplyreg"), [])
        reg = find(plan, "register pp_light")[0]
        self.assertIn("-interp=cubic", reg)
        self.assertNotIn("-2pass", reg)
        # フィルタは stack 側に付く
        stack = find(plan, "stack r_pp_light")[0]
        self.assertIn("-filter-wfwhm=3k", stack)

    def test_name_collision_gets_group_suffix(self):
        p = osc_cmos_project()
        p.lights += frames("L120", FrameKind.LIGHT, 4, exposure=120.0)
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        outs = [o.name for o in plan.outputs]
        self.assertEqual(outs, ["result_M31_g01", "result_M31_g02"])

    def test_two_sessions_merge(self):
        p = osc_cmos_project()
        night2 = frames("L2", FrameKind.LIGHT, 6)
        for f in p.lights:
            f.path = Path("/data/2026-09-10/lights") / f.path.name
        for f in night2:
            f.path = Path("/data/2026-09-11/lights") / f.path.name
        p.lights += night2
        flats2 = frames("F2", FrameKind.FLAT, 5, exposure=2.0)
        for f in p.flat_pool:
            f.path = Path("/data/2026-09-10/flats") / f.path.name
        for f in flats2:
            f.path = Path("/data/2026-09-11/flats") / f.path.name
        p.flat_pool += flats2
        grouping.build_groups(p)
        plan = build_plan(p, WORK)
        c = cmds(plan)
        # セッションごとにキャリブレーション（Flat は別、Dark は共通）
        cal = find(plan, "calibrate light")
        self.assertEqual(len(cal), 2)
        self.assertIn("-flat=../../masters/flat_01", cal[0])
        self.assertIn("-flat=../../masters/flat_02", cal[1])
        self.assertIn("-dark=../../masters/dark_01", cal[1])
        # merge して 1 本にスタック
        self.assertIn("merge ../g01/pp_light ../g02/pp_light pp_light", c)
        self.assertTrue(any(x.startswith('cd "') and x.endswith('/process/s01"') for x in c))
        self.assertEqual(len(find(plan, "register ")), 1)
        self.assertEqual(len(find(plan, "stack r_pp_light")), 1)
        self.assertEqual([o.name for o in plan.outputs], ["result_M31"])
        # merge は calibrate の後、register の前
        self.assertLess(c.index(cal[1]), c.index("merge ../g01/pp_light ../g02/pp_light pp_light"))
        self.assertLess(c.index("merge ../g01/pp_light ../g02/pp_light pp_light"), c.index(find(plan, "register ")[0]))

    def test_stack_methods(self):
        p = osc_cmos_project()
        grouping.build_groups(p)
        p.settings.stacking.method = "med"
        p.settings.stacking.weight = "noise"
        stack = find(build_plan(p, WORK), "stack r_pp_light")[0]
        self.assertTrue(stack.startswith("stack r_pp_light med -norm=addscale -rgb_equal -output_norm -32b"))
        self.assertNotIn("-weight", stack)
        p.settings.stacking.method = "sum"
        stack = find(build_plan(p, WORK), "stack r_pp_light")[0]
        self.assertEqual(stack, "stack r_pp_light sum -output_norm -32b -filter-included -out=../../output/result_M31")
        p.settings.stacking.method = "max"
        p.settings.stacking.output_norm = False
        stack = find(build_plan(p, WORK), "stack r_pp_light")[0]
        self.assertEqual(stack, "stack r_pp_light max -32b -filter-included -out=../../output/result_M31")

    def test_no_lights_raises(self):
        p = osc_cmos_project(n_light=0)
        grouping.build_groups(p)
        with self.assertRaises(PlanError):
            build_plan(p, WORK)

    def test_ssf_export(self):
        p = osc_cmos_project()
        grouping.build_groups(p)
        text = build_plan(p, WORK).to_ssf("header")
        self.assertIn("requires 1.4.0", text)
        self.assertIn("# [python]", text)

    def test_settings_roundtrip(self):
        s = Settings()
        s.drizzle.enabled = True
        s.registration.filter_round.value = 2.5
        d = s.to_dict()
        s2 = Settings.from_dict(d)
        self.assertTrue(s2.drizzle.enabled)
        self.assertEqual(s2.registration.filter_round.value, 2.5)
        # 未知キー・欠損キーに耐える
        s3 = Settings.from_dict({"stacking": {"rej_type": "g", "unknown": 1}, "bogus": {}})
        self.assertEqual(s3.stacking.rej_type, "g")
        self.assertEqual(s3.stacking.sigma_low, 3.0)


if __name__ == "__main__":
    unittest.main()
