#!/usr/bin/env python3
"""Unit tests of the coolingctld daemon — the project's functional specifications.

Covered specs:
  S1  HID protocol byte-for-byte identical to the reference controller
  S2  % -> RPM conversion: 500 + pct*27, steps of 50, clamp [0, 100]
  S3  linear curve interpolation (bounds = extreme points)
  S4  curve JSON loading (sorted curve, floor = first point)
  S5  key=value state file, complete fields, atomic writes
  S32 config self-provisioning: sensible defaults written on first start
      when missing (pacman never touches $HOME, the daemon provisions)
  S33 static color: QML color -> "#rrggbb" (native ColorButton)
  S34 LED packets byte-for-byte per padctl/openrazer + heat color ramp
      when missing (pacman never touches $HOME, the daemon provisions)
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(ROOT, "daemon", "coolingctld.py")
# Reference controller (historical HID protocol): path provided by
# COOLINGCTL_REFERENCE (e.g. a clone of razer-coolingpad-linux containing
# razer-coolingpad-fancurve.py). When absent -> the S1 parity tests are
# skipped, everything else stays active.
REFERENCE = os.environ.get("COOLINGCTL_REFERENCE", "")
REFERENCE = REFERENCE if os.path.isfile(REFERENCE) else ""


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = load_module(DAEMON, "coolingctld")
ref = load_module(REFERENCE, "fancurve") if REFERENCE else None


@unittest.skipUnless(ref is not None,
                     "reference controller absent (COOLINGCTL_REFERENCE)")
class TestProtocoleHID(unittest.TestCase):
    """S1: HID reports byte-for-byte on par with the reference."""

    def test_set_rpm_parity(self):
        for rpm in [500, 650, 800, 1310, 1500, 2000, 2700, 3200]:
            self.assertEqual(d.build_set_rpm_report(rpm),
                             ref.build_set_rpm_report(rpm), f"RPM {rpm}")

    def test_set_rpm_clamp(self):
        self.assertEqual(d.build_set_rpm_report(0), ref.build_set_rpm_report(500))
        self.assertEqual(d.build_set_rpm_report(9999), ref.build_set_rpm_report(3200))

    def test_off_parity(self):
        self.assertEqual(d.build_off_report(), ref.build_off_report())

    def test_taille_rapport(self):
        self.assertEqual(len(d.build_set_rpm_report(1500)), 91)
        self.assertEqual(len(d.build_off_report()), 91)


class TestConversions(unittest.TestCase):
    """S2: % -> RPM mapping."""

    def test_mapping_connu(self):
        cases = {0: 500, 30: 1300, 37: 1500, 50: 1850, 100: 3200}
        for pct, rpm in cases.items():
            self.assertEqual(d.pct_to_rpm(pct), rpm, f"pct {pct}")

    @unittest.skipUnless(ref is not None,
                         "reference controller absent (COOLINGCTL_REFERENCE)")
    def test_parity_reference(self):
        for pct in range(0, 101, 7):
            self.assertEqual(d.pct_to_rpm(pct), ref.percent_to_rpm(pct))

    def test_clamp(self):
        self.assertEqual(d.pct_to_rpm(-5), 500)
        self.assertEqual(d.pct_to_rpm(150), 3200)


class TestInterpolation(unittest.TestCase):
    """S3: curve interpolation."""

    CURVE = [(0, 0), (76, 0), (82, 20), (85, 35), (88, 55), (92, 75), (95, 90), (98, 100)]

    def test_sous_premier_point(self):
        self.assertEqual(d.interpolate(self.CURVE, -10), 0)

    def test_au_dernier_point(self):
        self.assertEqual(d.interpolate(self.CURVE, 200), 100)

    def test_entre_points(self):
        self.assertAlmostEqual(d.interpolate(self.CURVE, 79), 10.0)

    def test_point_exact(self):
        self.assertEqual(d.interpolate(self.CURVE, 85), 35)

    def test_empty_curve(self):
        self.assertIsNone(d.interpolate([], 50))


class TestConfig(unittest.TestCase):
    """S4: curve JSON loading."""

    def test_load_curve_triee(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"curve": [{"temp": 120, "percent": 30},
                                 {"temp": 0, "percent": 30}]}, f)
            path = f.name
        try:
            self.assertEqual(d.State.load_curve(path), [(0, 30.0), (120, 30.0)])
        finally:
            os.unlink(path)

    def test_load_floor(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"curve": [{"temp": 0, "percent": 30},
                                 {"temp": 120, "percent": 30}]}, f)
            path = f.name
        try:
            self.assertEqual(d.State.load_floor(path), 30.0)
        finally:
            os.unlink(path)

    def test_fichiers_absents(self):
        self.assertEqual(d.State.load_curve("/inexistant.json"), [])
        self.assertIsNone(d.State.load_floor("/inexistant.json"))


class TestStatusFile(unittest.TestCase):
    """S5: key=value state file, complete, atomic."""

    def _write(self, **kw):
        tmpdir = tempfile.mkdtemp()
        d.STATUS_FILE = os.path.join(tmpdir, "coolingctl.status")
        defaults = dict(mode="game", temp=63.5, floor_pct=30.0,
                        rpm_cmd=1300, rpm_rep=1300, pad_present=True)
        defaults.update(kw)
        d.write_status(**defaults)
        with open(d.STATUS_FILE) as f:
            content = f.read()
        return tmpdir, content

    def test_format_complet(self):
        tmpdir, content = self._write()
        try:
            for expected in ["mode=game", "temp=63.5", "floor_pct=30.0",
                           "floor_rpm=1300", "rpm_cmd=1300",
                           "rpm_reported=1300", "pad_present=1"]:
                self.assertIn(expected, content)
            self.assertNotIn(".tmp", os.listdir(tmpdir))  # atomicité
        finally:
            shutil.rmtree(tmpdir)

    def test_valeurs_absentes(self):
        tmpdir, content = self._write(mode="silent", temp=None,
                                      rpm_cmd=None, rpm_rep=None, pad_present=False)
        try:
            for expected in ["temp=-1", "rpm_cmd=-1", "rpm_reported=-1", "pad_present=0"]:
                self.assertIn(expected, content)
        finally:
            shutil.rmtree(tmpdir)


class TestDefaults(unittest.TestCase):
    """S32: config self-provisioning on first start."""
    def test_s32_defaults_created(self):
        tmpdir = tempfile.mkdtemp()
        try:
            d.ensure_configs(curves_dir=tmpdir)
            for name in ("silent-curve.json", "game-floor.json"):
                path = os.path.join(tmpdir, name)
                self.assertTrue(os.path.exists(path), f"{name} must be created")
                with open(path) as f:
                    data = json.load(f)
                self.assertIsInstance(data["curve"], list)
            # the floor file is a single-point curve: the first point IS the floor
            with open(os.path.join(tmpdir, "game-floor.json")) as f:
                floor = json.load(f)["curve"]
            self.assertEqual(len(floor), 1)
            self.assertIsInstance(floor[0]["percent"], (int, float))
            # idempotent: an existing config is never overwritten
            with open(os.path.join(tmpdir, "game-floor.json"), "w") as f:
                f.write('{"curve": [{"temp": 0, "percent": 50}]}')
            d.ensure_configs(curves_dir=tmpdir)
            with open(os.path.join(tmpdir, "game-floor.json")) as f:
                self.assertEqual(json.load(f)["curve"][0]["percent"], 50)
        finally:
            shutil.rmtree(tmpdir)


class TestLed(unittest.TestCase):
    """S34: LED packets replicate padctl/openrazer byte-for-byte (extended
    matrix, transaction id 0x1F, class 0x0F, XOR crc over buf[3..88])."""

    def _check_frame(self, report, cmd, size, args):
        self.assertEqual(len(report), 91)
        self.assertEqual(report[0], 0x00)        # report id
        self.assertEqual(report[2], 0x1F)        # RGB transaction id
        self.assertEqual(report[6], size)        # data size
        self.assertEqual(report[7], 0x0F)        # extended matrix class
        self.assertEqual(report[8], cmd)          # command
        for i, b in enumerate(args):
            self.assertEqual(report[9 + i], b, f"arg {i}")
        crc = 0
        for b in report[3:89]:
            crc ^= b
        self.assertEqual(report[89], crc, "crc must cover buf[3..88]")

    def test_s34_reports(self):
        self._check_frame(d.led_off_report(), 0x02, 0x06, [0x01, 0x00, 0x00])
        self._check_frame(d.led_spectrum_report(), 0x02, 0x06, [0x01, 0x00, 0x03])
        self._check_frame(d.led_static_report(0x12, 0x34, 0x56), 0x02, 0x09,
                          [0x01, 0x00, 0x01, 0x00, 0x00, 0x01, 0x12, 0x34, 0x56])
        self._check_frame(d.led_wave_report("left", 0x28), 0x02, 0x06,
                          [0x01, 0x00, 0x04, 0x01, 0x28])
        self._check_frame(d.led_wave_report("right"), 0x02, 0x06,
                          [0x01, 0x00, 0x04, 0x02, 0x28])
        self._check_frame(d.led_brightness_report(0x80), 0x04, 0x03,
                          [0x01, 0x00, 0x80])

    def test_s34_parse_led_color(self):
        self.assertEqual(d.parse_led_color("#ff6600"), (0xFF, 0x66, 0x00))
        self.assertEqual(d.parse_led_color("ff6600"), (0xFF, 0x66, 0x00))
        self.assertIsNone(d.parse_led_color("#ff660"))
        self.assertIsNone(d.parse_led_color("#zzzzzz"))
        self.assertIsNone(d.parse_led_color(None))

    def test_s34_heat_color(self):
        # thermal ramp anchors: cool = green, mid = yellow, hot = red
        self.assertEqual(d.heat_color(45), (0, 255, 0))
        self.assertEqual(d.heat_color(70), (255, 255, 0))
        self.assertEqual(d.heat_color(95), (255, 0, 0))
        # clamps outside the range
        self.assertEqual(d.heat_color(20), (0, 255, 0))
        self.assertEqual(d.heat_color(120), (255, 0, 0))
        # red rises monotonically, green falls monotonically
        prev_r, prev_g = -1, 256
        for t in range(45, 96, 5):
            r, g, b = d.heat_color(t)
            self.assertGreaterEqual(r, prev_r)
            self.assertLessEqual(g, prev_g)
            prev_r, prev_g = r, g

    def test_s34_heat_brightness(self):
        # 5 % when cool, 100 % in the danger zone (93 deg), linear, clamped
        self.assertEqual(d.heat_brightness(45), 5)
        self.assertEqual(d.heat_brightness(93), 100)
        self.assertEqual(d.heat_brightness(20), 5)
        self.assertEqual(d.heat_brightness(120), 100)
        # midpoint of the ramp (52.5 rounds to 52)
        self.assertEqual(d.heat_brightness(69), 52)
        # monotonic rise
        prev = 0
        for t in range(45, 94, 4):
            b = d.heat_brightness(t)
            self.assertGreaterEqual(b, prev)
            prev = b


class FakeDev:
    """Minimal hid.device stand-in: canned reads, writes recorded."""

    def __init__(self, report=None):
        self.report = report or bytearray(d.REPORT_LEN)
        self.written = []

    def get_feature_report(self, rid, length):
        return self.report[:length]

    def send_feature_report(self, report):
        self.written.append(bytes(report))
        return len(report)


class TestRpmRead(unittest.TestCase):
    """S38: read_rpm must reject buffer pollution (LED echo bug).

    The pad's feature report buffer echoes the last written frame; after
    an LED packet the brightness byte lands at IDX_RPM_L and decodes as
    garbage RPM (40% = byte 102 -> 5100 RPM, a lived bug)."""

    def _report(self, rpm):
        raw = rpm // 50
        buf = bytearray(d.REPORT_LEN)
        buf[0] = d.REPORT_ID
        buf[d.IDX_RPM_L] = raw & 0xFF
        buf[d.IDX_RPM_H] = (raw >> 8) & 0xFF
        return buf

    def test_s38_valid_telemetry(self):
        for rpm in [500, 800, 1500, 3200]:
            self.assertEqual(d.read_rpm(FakeDev(self._report(rpm))), rpm)

    def test_s38_rejects_led_echo(self):
        # 40% brightness = byte 102 at IDX_RPM_L -> 5100 RPM: pollution
        buf = bytearray(d.REPORT_LEN)
        buf[d.IDX_RPM_L] = 102
        self.assertIsNone(d.read_rpm(FakeDev(buf)))

    def test_s38_threshold(self):
        # MAX_RPM * 1.25 = 4000 is the last accepted value; beyond is junk
        self.assertEqual(d.read_rpm(FakeDev(self._report(4000))), 4000)
        self.assertIsNone(d.read_rpm(FakeDev(self._report(4050))))

    def test_s38_prime_rpm_frame(self):
        # after an LED write the caller must re-send the last fan frame
        frame = d.build_set_rpm_report(1500)
        dev = FakeDev()
        st = type("St", (), {})()
        st.last_frame = frame
        d.prime_rpm_frame(dev, st)
        self.assertEqual(dev.written[-1], bytes(frame))
        # no frame known: no write, no crash
        d.prime_rpm_frame(dev, type("St", (), {})())
        self.assertEqual(len(dev.written), 1)
        d.prime_rpm_frame(None, st)  # dev absent: silent no-op


if __name__ == "__main__":
    unittest.main()
