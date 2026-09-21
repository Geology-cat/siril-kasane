"""Dark が無いときの Bias / 黒レベルの自動補完（Flat の過補正防止）と黒レベル読取りのテスト"""

import struct
import tempfile
import unittest
from pathlib import Path

from kasane import grouping
from kasane.metadata.black_level import canon_black_level_index, plausible_black_level, read_black_level
from kasane.model import FrameKind, Settings
from kasane.pipeline import analyze, build_plan
from kasane.pipeline.offset import resolve_light_offset
from kasane.staging import WorkDirs
from tests.helpers import dslr_project, frame, osc_cmos_project

WORK = WorkDirs(Path("/work/Kasane_test"))


def light_cmd(plan) -> str:
    return next(s.command_text for s in plan.steps if s.kind == "cmd" and s.command_text.startswith("calibrate light"))


def dslr_no_dark(black: float | None = 2047.75):
    """Dark なし、既存マスター Flat あり、Bias なしの DSLR（Kasane 1.1 で過補正になった構成）"""
    p = dslr_project()
    p.dark_pool = []
    p.flat_pool = []
    p.flat_mode = "master_file"
    p.flat_master_path = Path("/data/LCPFlat.fits")
    p.bias_mode = "none"
    for f in p.lights:
        f.black_level = black
    return p


class AutoBiasTest(unittest.TestCase):
    def test_black_level_used_when_no_dark_and_no_bias(self):
        p = dslr_no_dark()
        grouping.build_groups(p)
        self.assertEqual(resolve_light_offset(p, p.groups[0]).mode, "auto_black")
        cmd = light_cmd(build_plan(p, WORK))
        self.assertIn('-bias="=2048"', cmd)
        self.assertIn("-flat=../../masters/flat_01", cmd)
        issues = analyze(p, None)
        self.assertTrue(any(i.level == "info" and "黒レベル 2048" in i.text for i in issues))

    def test_bias_master_file_is_applied_to_lights(self):
        """Bias マスターを指定しても Light に引かれなかった問題（use_bias_for_light=False のまま）"""
        p = dslr_no_dark()
        p.bias_mode = "master_file"
        p.bias_master_path = Path("/data/LCPBias.fits")
        grouping.build_groups(p)
        self.assertFalse(p.settings.calibration.use_bias_for_light)
        plan = build_plan(p, WORK)
        cmd = light_cmd(plan)
        self.assertIn("-bias=../../masters/bias_01", cmd)
        self.assertNotIn('-bias="=', cmd)  # 黒レベルより指定された Bias を優先
        # 既存マスターの Flat はキャリブレーションしない
        self.assertFalse(any(s.command_text.startswith("calibrate flat") for s in plan.steps if s.kind == "cmd"))

    def test_bias_constant_is_applied_to_lights(self):
        p = dslr_no_dark(black=None)
        p.bias_mode = "constant"
        p.bias_constant = 2000
        grouping.build_groups(p)
        self.assertIn('-bias="=2000"', light_cmd(build_plan(p, WORK)))

    def test_dark_present_no_bias(self):
        p = dslr_no_dark()
        p.dark_pool = [frame(f"IMG_D{i:04d}.CR2", FrameKind.DARK, source="raw", gain=1600.0, temp=None, size=None)
                       for i in range(5)]
        p.dark_mode = "frames"
        grouping.build_groups(p)
        self.assertEqual(resolve_light_offset(p, p.groups[0]).mode, "dark")
        cmd = light_cmd(build_plan(p, WORK))
        self.assertIn("-dark=", cmd)
        self.assertNotIn("-bias", cmd)

    def test_unknown_black_level_warns(self):
        p = dslr_no_dark(black=None)
        grouping.build_groups(p)
        self.assertEqual(resolve_light_offset(p, p.groups[0]).mode, "missing")
        self.assertNotIn("-bias", light_cmd(build_plan(p, WORK)))
        issues = analyze(p, None)
        self.assertTrue(any(i.level == "warn" and "過補正" in i.text for i in issues))

    def test_auto_disabled(self):
        p = dslr_no_dark()
        p.settings.calibration.auto_bias_without_dark = False
        grouping.build_groups(p)
        off = resolve_light_offset(p, p.groups[0])
        self.assertEqual(off.mode, "missing")
        self.assertTrue(off.auto_disabled)
        self.assertNotIn("-bias", light_cmd(build_plan(p, WORK)))

    def test_no_flat_no_auto_bias(self):
        p = dslr_no_dark()
        p.flat_mode = "none"
        grouping.build_groups(p)
        self.assertEqual(resolve_light_offset(p, p.groups[0]).mode, "not_needed")
        self.assertNotIn("-bias", light_cmd(build_plan(p, WORK)))

    def test_cmos_with_dark_unchanged(self):
        p = osc_cmos_project()
        grouping.build_groups(p)
        self.assertNotIn("-bias", light_cmd(build_plan(p, WORK)))

    def test_black_level_median_of_group(self):
        p = dslr_no_dark()
        for i, f in enumerate(p.lights):
            f.black_level = 2047.0 if i % 2 else 2049.0
        p.lights[0].black_level = None
        grouping.build_groups(p)
        self.assertEqual(resolve_light_offset(p, p.groups[0]).black_level, 2047.0)

    def test_settings_roundtrip(self):
        s = Settings()
        s.calibration.auto_bias_without_dark = False
        self.assertFalse(Settings.from_dict(s.to_dict()).calibration.auto_bias_without_dark)
        self.assertTrue(Settings.from_dict({}).calibration.auto_bias_without_dark)


def _tiff(entries: list[tuple[int, int, int, bytes]], base_offset: int) -> tuple[bytes, int]:
    """IFD を 1 つ作る（little endian）。entries = [(tag, type, count, 値のバイト列)]。(バイト列, IFD 長)"""
    n = len(entries)
    ifd_len = 2 + 12 * n + 4
    data_off = base_offset + ifd_len
    head = struct.pack("<H", n)
    extra = b""
    for tag, typ, count, value in entries:
        if len(value) <= 4:
            head += struct.pack("<HHI", tag, typ, count) + value.ljust(4, b"\0")
        else:
            head += struct.pack("<HHII", tag, typ, count, data_off + len(extra))
            extra += value + (b"\0" if len(value) % 2 else b"")
    head += struct.pack("<I", 0)
    return head + extra, ifd_len + len(extra)


class BlackLevelReaderTest(unittest.TestCase):
    def test_canon_index_table(self):
        self.assertEqual(canon_black_level_index(1273, 7), 479)  # EOS 6D（ColorData6）
        self.assertEqual(canon_black_level_index(1560, 14), 556)
        self.assertEqual(canon_black_level_index(1560, 13), 778)
        self.assertEqual(canon_black_level_index(3778, 0x41), 383)
        self.assertIsNone(canon_black_level_index(999, 0))

    def test_plausible(self):
        self.assertEqual(plausible_black_level([2050, 2051, 2045, 2045]), 2047.75)
        self.assertIsNone(plausible_black_level([2048, 0, 2048, 2048]))
        self.assertIsNone(plausible_black_level([2048, 9000, 2048, 2048]))

    def test_synthetic_canon_cr2(self):
        """IFD0(Make=Canon) → Exif IFD → MakerNote → ColorData(1273 要素, 479 に黒レベル) の最小 TIFF"""
        color = [0] * 1273
        color[0] = 7
        color[479:483] = [2050, 2051, 2045, 2045]
        color_bytes = struct.pack("<1273H", *color)
        # 配置: ヘッダ(8) → IFD0 → Exif IFD → MakerNote IFD
        make = b"Canon\0"
        ifd0_off = 8
        # まず長さを求めるため仮に作る
        ifd0, ifd0_len = _tiff([(0x010F, 2, len(make), make), (0x8769, 4, 1, struct.pack("<I", 0))], ifd0_off)
        exif_off = ifd0_off + ifd0_len
        exif, exif_len = _tiff([(0x927C, 7, 1, b"\0\0\0\0")], exif_off)
        mn_off = exif_off + exif_len
        mn, _ = _tiff([(0x4001, 3, 1273, color_bytes)], mn_off)
        # 正しいオフセットで作り直す
        ifd0, _ = _tiff([(0x010F, 2, len(make), make), (0x8769, 4, 1, struct.pack("<I", exif_off))], ifd0_off)
        exif, _ = _tiff([(0x927C, 7, len(mn), struct.pack("<I", mn_off))], exif_off)
        # MakerNote は UNDEFINED 型で本体の位置を値として持つ（count > 4 なのでオフセット扱い）
        exif = exif[:2] + struct.pack("<HHII", 0x927C, 7, len(mn), mn_off) + exif[14:]
        data = b"II*\0" + struct.pack("<I", ifd0_off) + ifd0 + exif + mn
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "test.CR2"
            path.write_bytes(data)
            self.assertEqual(read_black_level(path), 2047.75)

    def test_not_raw(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.CR2"
            path.write_bytes(b"not a tiff" * 100)
            self.assertIsNone(read_black_level(path))
            self.assertIsNone(read_black_level(Path(d) / "missing.CR2"))


class WorkRootTest(unittest.TestCase):
    def test_effective_work_root_defaults_to_light_folder(self):
        p = dslr_project()
        p.work_root = None
        for f in p.lights:
            f.path = Path("/data/TEST") / f.path.name
        self.assertEqual(p.effective_work_root(), Path("/data/TEST/output"))
        p.work_root = Path("/somewhere")
        self.assertEqual(p.effective_work_root(), Path("/somewhere"))

    def test_lights_subfolder(self):
        p = dslr_project()
        p.work_root = None
        p.target_name = ""
        for f in p.lights:
            f.path = Path("/data/M31/lights") / f.path.name
        self.assertEqual(p.effective_work_root(), Path("/data/M31/output"))
        self.assertEqual(p.effective_target_name(), "M31")

    def test_no_lights(self):
        from kasane.model import Project

        self.assertIsNone(Project().effective_work_root())


if __name__ == "__main__":
    unittest.main()
