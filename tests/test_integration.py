#!/usr/bin/env python3
"""Integration tests against the LIVE daemon (coolingctl user service).

Skipped when the daemon is not running (CI without the machine).

Covered specs:
  S9  the state file is published and schema-valid continuously
  S10 mode switching by signal without a restart (NRestarts unchanged)
  S11 floor modified hot without restarting the daemon
"""
import os
import re
import subprocess
import time
import unittest

STATUS_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"),
                           "coolingctl.status")
GAMING_JSON = os.path.join(os.environ.get(
    "XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "coolingctl", "game-floor.json")
KEYS = {"mode", "temp", "floor_pct", "floor_rpm", "led", "led_brightness", "led_color",
        "rpm_cmd", "rpm_reported", "pad_present"}


def daemon_active():
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "coolingctl"],
                           capture_output=True, text=True)
        return r.stdout.strip() == "active" and os.path.exists(STATUS_FILE)
    except OSError:
        return False


def read_status():
    fields = {}
    with open(STATUS_FILE) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if _:
                fields[k] = v
    return fields


def signal_daemon(sig):
    subprocess.run(["systemctl", "--user", "kill", f"--signal={sig}",
                   "coolingctl"], check=True)


def wait_for(predicate, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.5)
    return False


@unittest.skipUnless(daemon_active(), "coolingctl daemon not active")
class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial_state = read_status()
        cls.initial_floor = cls._read_floor()

    @classmethod
    def tearDownClass(cls):
        # full restoration of the initial state
        floor = cls.initial_floor
        with open(GAMING_JSON) as f:
            content = f.read()
        with open(GAMING_JSON, "w") as f:
            f.write(re.sub(r'"percent": *[0-9]*', f'"percent": {floor}', content))
        signal_daemon("SIGHUP")  # resync the daemon with the restored file
        mode = cls.initial_state["mode"]
        sig = {"game": "SIGUSR1", "silent": "SIGUSR2", "free": "SIGWINCH"}[mode]
        signal_daemon(sig)

    @staticmethod
    def _read_floor():
        with open(GAMING_JSON) as f:
            content = f.read()
        m = re.search(r'"percent": *([0-9]+)', content)
        return int(m.group(1))

    @staticmethod
    def _nrestarts():
        r = subprocess.run(["systemctl", "--user", "show", "coolingctl",
                            "-p", "NRestarts"], capture_output=True, text=True)
        return int(r.stdout.strip().split("=")[1])

    def test_s9_schema_status(self):
        fields = read_status()
        self.assertTrue(KEYS.issubset(fields), fields)
        self.assertIn(fields["mode"], {"silent", "game", "free"})
        float(fields["temp"])
        float(fields["floor_pct"])
        int(fields["rpm_cmd"])
        int(fields["rpm_reported"])
        self.assertIn(fields["pad_present"], {"0", "1"})
        self.assertIn(fields["led"], {"keep", "off", "static", "spectrum", "wave", "heat"})
        int(fields["led_brightness"])
        self.assertRegex(fields["led_color"], r"^#[0-9a-fA-F]{6}$")

    def test_s10_mode_switch_without_restart(self):
        n0 = self._nrestarts()
        signal_daemon("SIGUSR1")
        self.assertTrue(wait_for(lambda: read_status()["mode"] == "game"),
                        "game mode not reached")
        signal_daemon("SIGUSR2")
        self.assertTrue(wait_for(lambda: read_status()["mode"] == "silent"),
                        "silent mode not reached")
        self.assertEqual(self._nrestarts(), n0, "the daemon restarted!")

    def test_s11_hot_floor_write(self):
        n0 = self._nrestarts()
        with open(GAMING_JSON) as f:
            content = f.read()
        with open(GAMING_JSON, "w") as f:
            f.write(re.sub(r'"percent": *[0-9]*', '"percent": 33', content))
        signal_daemon("SIGHUP")
        self.assertTrue(
            wait_for(lambda: read_status()["floor_rpm"] == "1400"),
            f"floor_rpm={read_status().get('floor_rpm')} != 1400")
        self.assertEqual(self._nrestarts(), n0, "the daemon restarted!")


if __name__ == "__main__":
    unittest.main()
