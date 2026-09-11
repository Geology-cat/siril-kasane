import struct
import tempfile
import unittest
from pathlib import Path

from kasane.metadata import fits_reader
from kasane.metadata.reader import read_frame
from kasane.model import FrameKind


def _card(key: str, value, comment: str = "") -> bytes:
    if isinstance(value, bool):
        v = "T" if value else "F"
        body = f"{key:<8}= {v:>20}"
    elif isinstance(value, (int, float)):
        body = f"{key:<8}= {value!r:>20}"
    else:
        s = str(value).replace("'", "''")
        body = f"{key:<8}= '{s:<8}'"
    if comment:
        body += f" / {comment}"
    return body.ljust(80)[:80].encode("ascii")


def write_fits(path: Path, cards: dict, width: int = 4, height: int = 3, planes: int = 1) -> None:
    header = b"".join(
        [
            _card("SIMPLE", True),
            _card("BITPIX", 16),
            _card("NAXIS", 3 if planes > 1 else 2),
            _card("NAXIS1", width),
            _card("NAXIS2", height),
        ]
        + ([_card("NAXIS3", planes)] if planes > 1 else [])
        + [_card(k, v) for k, v in cards.items()]
        + [b"END".ljust(80)]
    )
    header += b" " * ((2880 - len(header) % 2880) % 2880)
    data = struct.pack(f">{width * height * planes}h", *([100] * (width * height * planes)))
    data += b"\0" * ((2880 - len(data) % 2880) % 2880)
    path.write_bytes(header + data)


class FitsReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_osc_cmos_header(self):
        p = self.dir / "light.fit"
        write_fits(
            p,
            {
                "EXPTIME": 180.0,
                "GAIN": 100,
                "OFFSET": 50,
                "BAYERPAT": "RGGB",
                "CCD-TEMP": -9.8,
                "XBINNING": 1,
                "DATE-OBS": "2026-09-10T14:03:22.123",
                "IMAGETYP": "Light Frame",
                "INSTRUME": "ZWO ASI2600MC Pro",
            },
        )
        f = read_frame(p, FrameKind.LIGHT)
        self.assertIsNone(f.error)
        self.assertEqual(f.source, "fits")
        self.assertEqual(f.sensor, "osc")
        self.assertEqual(f.bayer_pattern, "RGGB")
        self.assertEqual(f.exposure, 180.0)
        self.assertEqual(f.iso_or_gain, 100)
        self.assertEqual(f.offset, 50)
        self.assertAlmostEqual(f.temperature, -9.8)
        self.assertEqual(f.binning, 1)
        self.assertEqual(f.size, (4, 3))
        self.assertEqual(f.date_obs.year, 2026)
        self.assertEqual(f.image_type, "light")
        self.assertEqual(f.instrument, "ZWO ASI2600MC Pro")

    def test_mono_header_and_aliases(self):
        p = self.dir / "flat.fits"
        write_fits(p, {"EXPOSURE": 3.5, "EGAIN": 1.2, "FILTER": "Ha", "IMAGETYP": "FLAT", "CCDTEMP": -5})
        f = read_frame(p, FrameKind.FLAT)
        self.assertEqual(f.sensor, "mono")
        self.assertEqual(f.exposure, 3.5)
        self.assertEqual(f.iso_or_gain, 1.2)
        self.assertEqual(f.filter, "Ha")
        self.assertEqual(f.image_type, "flat")
        self.assertEqual(f.temperature, -5)

    def test_image_type_variants(self):
        n = fits_reader.normalize_image_type
        self.assertEqual(n("Dark Flat"), "darkflat")
        self.assertEqual(n("FLATDARK"), "darkflat")
        self.assertEqual(n("Bias Frame"), "bias")
        self.assertEqual(n("zero"), "bias")
        self.assertEqual(n("LIGHT"), "light")
        self.assertEqual(n("Dark"), "dark")
        self.assertIsNone(n("something"))

    def test_string_with_quote_and_comment(self):
        self.assertEqual(fits_reader._parse_value("'O''Neil  ' / comment"), "O'Neil")
        self.assertEqual(fits_reader._parse_value("  1.5E+02 / exposure"), 150.0)
        self.assertEqual(fits_reader._parse_value("T"), True)

    def test_three_plane_is_osc(self):
        p = self.dir / "rgb.fit"
        write_fits(p, {"EXPTIME": 10}, planes=3)
        f = read_frame(p, FrameKind.LIGHT)
        self.assertEqual(f.sensor, "osc")

    def test_not_fits(self):
        p = self.dir / "bad.fit"
        p.write_bytes(b"not a fits file" * 100)
        f = read_frame(p, FrameKind.LIGHT)
        self.assertIsNotNone(f.error)


if __name__ == "__main__":
    unittest.main()
