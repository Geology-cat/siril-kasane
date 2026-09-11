import unittest

from kasane import grouping
from kasane.model import FrameKind, MasterSource
from tests.helpers import dslr_project, frame, frames, mono_project, osc_cmos_project


class GroupingTest(unittest.TestCase):
    def test_single_group_osc(self):
        p = osc_cmos_project()
        groups = grouping.build_groups(p)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g.group_id, "g01")
        self.assertEqual(len(g.frames), 10)
        self.assertEqual(g.dark.mode, "frames")
        self.assertEqual(len(g.dark.frames), 5)
        self.assertEqual(g.dark.note, "")
        self.assertEqual(g.flat.mode, "frames")
        self.assertEqual(g.darkflat.mode, "frames")
        self.assertEqual(g.darkflat.frames[0].exposure, 2.0)

    def test_mono_filters_split_and_match(self):
        p = mono_project()
        groups = grouping.build_groups(p)
        self.assertEqual([g.key.filter for g in groups], ["Ha", "OIII"])
        ha, oiii = groups
        self.assertTrue(all(f.filter == "Ha" for f in ha.flat.frames))
        self.assertTrue(all(f.filter == "OIII" for f in oiii.flat.frames))
        # Dark Flat は Flat の露出に合わせる
        self.assertEqual(ha.darkflat.frames[0].exposure, 3.0)
        self.assertEqual(oiii.darkflat.frames[0].exposure, 5.0)
        # Dark は共通
        self.assertEqual(ha.dark.frames, oiii.dark.frames)

    def test_dark_exposure_mismatch_warns(self):
        p = osc_cmos_project()
        p.dark_pool = frames("D", FrameKind.DARK, 5, exposure=120.0)
        g = grouping.build_groups(p)[0]
        self.assertEqual(g.dark.mode, "frames")
        self.assertIn("露出不一致", g.dark.note)

    def test_dark_prefers_matching_exposure_and_temp(self):
        p = osc_cmos_project()
        p.dark_pool = (
            frames("D120", FrameKind.DARK, 5, exposure=120.0)
            + frames("D180warm", FrameKind.DARK, 5, exposure=180.0, temp=0.0)
            + frames("D180", FrameKind.DARK, 5, exposure=180.0, temp=-10.0)
        )
        g = grouping.build_groups(p)[0]
        self.assertTrue(all(f.name.startswith("D180_") for f in g.dark.frames))
        self.assertEqual(g.dark.note, "")

    def test_size_mismatch_excludes(self):
        p = osc_cmos_project()
        p.dark_pool = frames("D", FrameKind.DARK, 5, size=(3000, 2000))
        g = grouping.build_groups(p)[0]
        self.assertEqual(g.dark.mode, "none")

    def test_flat_filter_missing(self):
        p = mono_project()
        p.flat_pool = frames("F_Ha", FrameKind.FLAT, 5, sensor="mono", filt="Ha", exposure=3.0)
        groups = grouping.build_groups(p)
        self.assertEqual(groups[0].flat.mode, "frames")
        self.assertEqual(groups[1].flat.mode, "none")
        self.assertIn("OIII", groups[1].flat.note)

    def test_dslr_groups_by_iso_and_exposure_only(self):
        p = dslr_project()
        p.lights += [
            f for f in frames("ISO800", FrameKind.LIGHT, 3, source="raw", gain=800.0, temp=None, size=None, filt=None)
        ]
        groups = grouping.build_groups(p)
        self.assertEqual(len(groups), 2)
        # ISO1600 の Dark しか無いので ISO800 グループには Gain 不一致の警告付きで割り当たる
        g800 = next(g for g in groups if g.key.iso_or_gain == 800.0)
        self.assertEqual(g800.dark.mode, "frames")
        self.assertIn("Gain/ISO 不一致", g800.dark.note)
        self.assertEqual(g800.bias.mode, "constant")

    def test_global_master_file_and_override(self):
        from pathlib import Path

        p = osc_cmos_project()
        p.dark_mode = "master_file"
        p.dark_master_path = Path("/lib/master_dark_180s.fit")
        p.overrides["g01"] = {"flat": MasterSource(mode="master_file", master_path=Path("/lib/flat.fit"), auto=False)}
        g = grouping.build_groups(p)[0]
        self.assertEqual(g.dark.mode, "master_file")
        self.assertEqual(g.flat.master_path, Path("/lib/flat.fit"))

    def test_classify_by_image_type(self):
        fs = frames("x", FrameKind.LIGHT, 2, image_type="dark") + frames("y", FrameKind.LIGHT, 1, image_type="flat")
        out = grouping.classify_by_image_type(fs)
        self.assertEqual(len(out[FrameKind.DARK]), 2)
        self.assertEqual(len(out[FrameKind.FLAT]), 1)
        self.assertEqual(out[FrameKind.DARK][0].kind, FrameKind.DARK)

    def test_session_by_folder(self):
        from pathlib import Path

        p = osc_cmos_project()
        night1 = [frame(f"L1_{i}.fit", FrameKind.LIGHT) for i in range(4)]
        night2 = [frame(f"L2_{i}.fit", FrameKind.LIGHT) for i in range(4)]
        for f in night1:
            f.path = Path("/data/2026-09-10/lights") / f.path.name
        for f in night2:
            f.path = Path("/data/2026-09-11/lights") / f.path.name
        p.lights = night1 + night2
        flats1 = frames("F1", FrameKind.FLAT, 3, exposure=2.0)
        flats2 = frames("F2", FrameKind.FLAT, 3, exposure=2.0)
        for f in flats1:
            f.path = Path("/data/2026-09-10/flats") / f.path.name
        for f in flats2:
            f.path = Path("/data/2026-09-11/flats") / f.path.name
        p.flat_pool = flats1 + flats2
        for f in p.dark_pool + p.darkflat_pool:
            f.path = Path("/lib/darks") / f.path.name  # 共通ライブラリ
        groups = grouping.build_groups(p)
        self.assertEqual(grouping.effective_session_mode(p), "folder")
        self.assertEqual(len(groups), 2)
        self.assertEqual([g.session_label for g in groups], ["2026-09-10", "2026-09-11"])
        self.assertTrue(all(f.name.startswith("F1_") for f in groups[0].flat.frames))
        self.assertTrue(all(f.name.startswith("F2_") for f in groups[1].flat.frames))
        self.assertEqual(groups[0].flat.note, "")
        # 共通 Dark はセッション情報が別でも警告なしで割り当たる
        self.assertEqual(groups[0].dark.mode, "frames")
        self.assertEqual(groups[0].dark.note, "")
        # 同じキーなので planner ではまとめて 1 本になる
        self.assertEqual(groups[0].key, groups[1].key)

    def test_session_by_date_when_single_folder(self):
        from datetime import datetime

        p = osc_cmos_project()
        for i, f in enumerate(p.lights):
            f.date_obs = datetime(2026, 9, 10 + (i // 5), 23, 30) if i % 5 != 4 else datetime(2026, 9, 11 + (i // 5), 2, 0)
        groups = grouping.build_groups(p)
        self.assertEqual(grouping.effective_session_mode(p), "date")
        self.assertEqual([g.session for g in groups], ["2026-09-10", "2026-09-11"])
        self.assertEqual([len(g.frames) for g in groups], [5, 5])
        p.session_mode = "none"
        self.assertEqual(len(grouping.build_groups(p)), 1)

    def test_flat_session_mismatch_warns(self):
        from pathlib import Path

        p = osc_cmos_project()
        for f in p.lights:
            f.path = Path("/data/n1/lights") / f.path.name
        p.lights += [frame(f"X_{i}.fit", FrameKind.LIGHT) for i in range(3)]
        for f in p.lights[-3:]:
            f.path = Path("/data/n2/lights") / f.path.name
        for f in p.flat_pool:
            f.path = Path("/data/n1/flats") / f.path.name
        groups = grouping.build_groups(p)
        self.assertEqual(groups[0].flat.note, "")
        self.assertIn("セッション不一致", groups[1].flat.note)


if __name__ == "__main__":
    unittest.main()
