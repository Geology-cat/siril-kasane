import tempfile
import unittest
from pathlib import Path

from kasane import grouping
from kasane.model import Project
from kasane.model.presets import PresetStore
from kasane.pipeline import analyze
from tests.helpers import dslr_project, mono_project, osc_cmos_project


class ProjectTest(unittest.TestCase):
    def test_roundtrip_json(self):
        p = osc_cmos_project()
        grouping.build_groups(p)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            p.save(path)
            q = Project.load(path)
        self.assertEqual(len(q.lights), 10)
        self.assertEqual(q.groups[0].dark.frames[0].path, p.groups[0].dark.frames[0].path)
        self.assertEqual(q.settings.calibration.flat_calib_mode, "darkflat")
        self.assertEqual(q.work_root, p.work_root)

    def test_sensor_detection(self):
        self.assertEqual(osc_cmos_project().sensor, "osc")
        self.assertEqual(mono_project().sensor, "mono")
        self.assertEqual(dslr_project().sensor, "osc")
        p = mono_project()
        p.sensor_override = "osc"
        self.assertTrue(p.is_osc)

    def test_analyze_reports(self):
        p = osc_cmos_project()
        p.dark_pool = []
        grouping.build_groups(p)
        issues = analyze(p, Path("/tmp/Kasane_x"))
        self.assertTrue(any(i.level == "warn" and "Dark がありません" in i.text for i in issues))
        self.assertFalse(any(i.level == "error" for i in issues))

        p = dslr_project()
        p.bias_mode = "offset_keyword"
        grouping.build_groups(p)
        issues = analyze(p, Path("/tmp/Kasane_x"))
        self.assertTrue(any(i.level == "error" and "OFFSET" in i.text for i in issues))

    def test_presets(self):
        with tempfile.TemporaryDirectory() as d:
            store = PresetStore(Path(d))
            names = store.list_names()
            self.assertIn("DSLR OSC 標準", names)
            s = store.load("CMOS Mono 標準")
            self.assertFalse(s.stacking.rgb_equal)
            s.drizzle.enabled = True
            store.save("mine", s)
            self.assertIn("mine", store.list_names())
            self.assertTrue(store.load("mine").drizzle.enabled)
            store.delete("mine")
            self.assertNotIn("mine", store.list_names())


if __name__ == "__main__":
    unittest.main()
