#!/usr/bin/env python3
"""Tests of the coolingctl.sh helper — the plasmoid's interface contract.
Covered specs:
  S6  `status` : ligne à 9 champs tctl|fan1|fan2|pad_rpm|mode|floor_pct|gpu|cpu|gpu_pct
      mode passthrough: silent|game|free (fallback silent);
      pad_rpm and floor come from the state file; absent -> -1
  S7  `set-floor N`: writes the floor into the json (clamped 0..100),
      bounded, invalid rejected; sends SIGHUP to the daemon
  S8  `mode X`: SIGUSR1 (game), SIGUSR2 (silent), SIGWINCH (free);
      invalid mode rejected
  S35 `led X`: rewrites led.json (effect, static color, wave direction,
      brightness clamped 0..100) and SIGHUPs; status carries the LED effect
      as its 10th field
Materialized through a fake environment: temporary XDG_RUNTIME_DIR,
temporary curve json (COOLINGCTL_GAMING_JSON), a fake systemctl
in the PATH that logs its arguments.
"""
import os
import json
import shutil
import stat
import subprocess
import tempfile
import unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "plasmoid", "org.coolingctl",
                      "contents", "code", "coolingctl.sh")
class FakeEnv:
    def __init__(self, status_content=None):
        self.tmp = tempfile.mkdtemp()
        self.xdg = os.path.join(self.tmp, "xdg")
        self.fakebin = os.path.join(self.tmp, "bin")
        self.sysctl_log = os.path.join(self.tmp, "systemctl.log")
        self.gaming_json = os.path.join(self.tmp, "game-floor.json")
        os.makedirs(self.xdg)
        os.makedirs(self.fakebin)
        # canonical config directory, like a real installation
        os.makedirs(os.path.join(self.tmp, "config", "coolingctl"))
        # fake DRM tree: device = symlink to the PCI path, like in /sys
        self.drm = os.path.join(self.tmp, "drm")
        igpu_pci = os.path.join(self.tmp, "pci", "c4:00.0")
        os.makedirs(igpu_pci)
        with open(os.path.join(igpu_pci, "gpu_busy_percent"), "w") as f:
            f.write("55\n")
        os.makedirs(os.path.join(self.tmp, "pci", "03:00.0"))
        os.makedirs(os.path.join(self.drm, "card2"))
        os.symlink(igpu_pci, os.path.join(self.drm, "card2", "device"))
        os.makedirs(os.path.join(self.drm, "card1"))
        os.symlink(os.path.join(self.tmp, "pci", "03:00.0"),
                   os.path.join(self.drm, "card1", "device"))
        fake = "#!/bin/sh\necho \"$@\" >> \"" + self.sysctl_log + "\"\n"
        fake_path = os.path.join(self.fakebin, "systemctl")
        with open(fake_path, "w") as f:
            f.write(fake)
        os.chmod(fake_path, os.stat(fake_path).st_mode | stat.S_IEXEC)
        with open(self.gaming_json, "w") as f:
            json.dump({"curve": [{"temp": 0, "percent": 30},
                                 {"temp": 120, "percent": 30}]}, f)
        self.led_json = os.path.join(self.tmp, "led.json")
        with open(self.led_json, "w") as f:
            json.dump({"effect": "keep", "color": "#ff6600",
                       "brightness": 100, "wave_dir": "right",
                       "wave_speed": 40}, f)
        if status_content is not None:
            with open(os.path.join(self.xdg, "coolingctl.status"), "w") as f:
                f.write(status_content)
    @property
    def env(self):
        e = os.environ.copy()
        e["XDG_RUNTIME_DIR"] = self.xdg
        e["PATH"] = self.fakebin + ":" + e["PATH"]
        e["XDG_CONFIG_HOME"] = os.path.join(self.tmp, "config")
        e["COOLINGCTL_GAMING_JSON"] = self.gaming_json
        e["COOLINGCTL_LED_JSON"] = self.led_json
        e["COOLINGCTL_DRM_DIR"] = self.drm
        e.pop("LD_LIBRARY_PATH", None)
        return e
    def env_par_defaut(self):
        """Environment WITHOUT overrides: the helper must resolve
        XDG_CONFIG_HOME/coolingctl/game-floor.json on its own."""
        e = self.env
        e.pop("COOLINGCTL_GAMING_JSON")
        return e
    def run_par_defaut(self, *args):
        return subprocess.run(["sh", HELPER, *args], env=self.env_par_defaut(),
                              capture_output=True, text=True, timeout=10)
    def run(self, *args):
        return subprocess.run(["sh", HELPER, *args], env=self.env,
                              capture_output=True, text=True, timeout=10)
    def floor(self):
        with open(self.gaming_json) as f:
            return json.load(f)["curve"][0]["percent"]
    def systemctl_calls(self):
        try:
            with open(self.sysctl_log) as f:
                return f.read()
        except OSError:
            return ""
    def cleanup(self):
        shutil.rmtree(self.tmp)
class TestStatus(unittest.TestCase):
    """S6: status format and mapping."""
    def test_9_champs(self):
        env = FakeEnv("mode=silent\ntemp=60.0\nfloor_pct=30.0\n"
                      "floor_rpm=1300\nrpm_cmd=500\nrpm_reported=500\npad_present=1\n")
        try:
            r = env.run("status")
            self.assertEqual(r.returncode, 0, r.stderr)
            champs = r.stdout.strip().split("|")
            self.assertEqual(len(champs), 12, champs)
            self.assertEqual(champs[3], "500")        # pad_rpm
            self.assertEqual(champs[4], "silent")  # curve -> silent
            self.assertEqual(champs[5], "30.0")        # floor
            self.assertRegex(champs[7], r"^[0-9]+$")    # CPU load 0..100
            self.assertRegex(champs[8], r"^-?[0-9]+$")  # GPU load (-1 when absent)
        finally:
            env.cleanup()
    def test_mode_game_and_free(self):
        for mode, expected in [("game", "game"), ("free", "free")]:
            env = FakeEnv(f"mode={mode}\nrpm_reported=1300\nfloor_pct=30\n")
            try:
                champs = env.run("status").stdout.strip().split("|")
                self.assertEqual(champs[4], expected)
                self.assertEqual(champs[9], "keep")   # no led= in the file
                self.assertEqual(champs[10], "100")  # brightness defaults
                self.assertEqual(champs[11], "#ff6600")  # color defaults
            finally:
                env.cleanup()
    def test_led_field_passthrough(self):
        env = FakeEnv("mode=silent\nrpm_reported=1300\nfloor_pct=30\nled=heat\n")
        try:
            champs = env.run("status").stdout.strip().split("|")
            self.assertEqual(champs[9], "heat")
        finally:
            env.cleanup()
class TestLed(unittest.TestCase):
    """S35: `led` command rewrites led.json and SIGHUPs the daemon."""
    def led_cfg(self):
        env = FakeEnv()
        try:
            return env, json.load(open(env.led_json))
        finally:
            pass
    def test_effects(self):
        for effect in ["off", "spectrum", "heat", "keep"]:
            env = FakeEnv()
            try:
                r = env.run("led", effect)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(env.led_json) as f:
                    self.assertEqual(json.load(f)["effect"], effect)
                self.assertIn("SIGHUP", env.systemctl_calls())
            finally:
                env.cleanup()
    def test_static_color(self):
        # with or without the leading '#': the exec transport swallows a
        # raw '#' as a shell comment, the QML sends the plain hex
        for raw, written in [("#00ffaa", "#00ffaa"), ("00ffaa", "#00ffaa")]:
            env = FakeEnv()
            try:
                r = env.run("led", "static", raw)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(env.led_json) as f:
                    cfg = json.load(f)
                self.assertEqual(cfg["effect"], "static")
                self.assertEqual(cfg["color"], written)
            finally:
                env.cleanup()

    def test_static_without_color_keeps_last(self):
        # selecting Static from the ComboBox sends no color: the effect
        # switches and the previously picked color is preserved
        env = FakeEnv()
        try:
            r = env.run("led", "static", "#b455e0")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = env.run("led", "static")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(env.led_json) as f:
                cfg = json.load(f)
            self.assertEqual(cfg["effect"], "static")
            self.assertEqual(cfg["color"], "#b455e0")
        finally:
            env.cleanup()
    def test_static_invalid_color(self):
        env = FakeEnv()
        try:
            r = env.run("led", "static", "green")
            self.assertNotEqual(r.returncode, 0)
        finally:
            env.cleanup()
    def test_wave_direction(self):
        env = FakeEnv()
        try:
            r = env.run("led", "wave", "left")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(env.led_json) as f:
                cfg = json.load(f)
            self.assertEqual(cfg["effect"], "wave")
            self.assertEqual(cfg["wave_dir"], "left")
        finally:
            env.cleanup()
    def test_brightness_clamps(self):
        # same contract as set-floor: negatives are invalid input, high clamps
        for raw, expected in [("150", 100), ("60", 60)]:
            env = FakeEnv()
            try:
                r = env.run("led", "bright", raw)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(env.led_json) as f:
                    self.assertEqual(json.load(f)["brightness"], expected)
            finally:
                env.cleanup()
        env = FakeEnv()
        try:
            r = env.run("led", "bright", "-3")
            self.assertNotEqual(r.returncode, 0)
        finally:
            env.cleanup()
    def test_invalid_led_mode(self):
        env = FakeEnv()
        try:
            r = env.run("led", "strobe")
            self.assertNotEqual(r.returncode, 0)
        finally:
            env.cleanup()
    def test_status_absent(self):
        env = FakeEnv()  # no state file
        try:
            champs = env.run("status").stdout.strip().split("|")
            self.assertEqual(champs[3], "-1")
            self.assertEqual(champs[4], "silent")
            self.assertEqual(champs[5], "-1")
        finally:
            env.cleanup()
    def test_cpu_delta(self):
        """S16: CPU load = /proc/stat delta, primed then a 0..100 value."""
        env = FakeEnv()
        try:
            env.run("status")  # amorçage (premier appel : delta impossible)
            champs = env.run("status").stdout.strip().split("|")
            cpu = int(champs[7])
            self.assertGreaterEqual(cpu, 0)
            self.assertLessEqual(cpu, 100)
        finally:
            env.cleanup()
    def test_gpu_pct_hermetique(self):
        """S25: GPU load read from the fake DRM tree (iGPU, sleeping dGPU)."""
        env = FakeEnv()
        try:
            champs = env.run("status").stdout.strip().split("|")
            self.assertEqual(champs[8], "55")  # the fake value, not the real hardware
        finally:
            env.cleanup()
    def test_chemins_par_defaut(self):
        """S17: without env overrides, the helper resolves
        XDG_CONFIG_HOME/coolingctl/game-floor.json (canonical names)."""
        env = FakeEnv()
        try:
            canonique = os.path.join(env.env["XDG_CONFIG_HOME"],
                                     "coolingctl", "game-floor.json")
            # an existing installation: the config file is already there
            shutil.copy(env.gaming_json, canonique)
            r = env.run_par_defaut("set-floor", "25")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(canonique),
                            f"the helper did not resolve the default path: {canonique}")
            with open(canonique) as f:
                self.assertIn('"percent": 25', f.read())
        finally:
            env.cleanup()
class TestSetFloor(unittest.TestCase):
    """S7: floor write + SIGHUP."""
    def test_ecriture_et_signal(self):
        env = FakeEnv()
        try:
            r = env.run("set-floor", "40")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(env.floor(), 40)
            self.assertIn("--user kill --signal=SIGHUP coolingctl.service",
                          env.systemctl_calls())
        finally:
            env.cleanup()
    def test_clamp(self):
        env = FakeEnv()
        try:
            env.run("set-floor", "2")
            self.assertEqual(env.floor(), 2)   # 0..100 valide : plus de clamp a 5
            self.assertEqual(env.run("set-floor", "0").returncode, 0)
            self.assertEqual(env.floor(), 0)   # plancher 0 % = 500 RPM
            self.assertNotEqual(env.run("set-floor", "-3").returncode, 0)  # non numerique : rejete
            env.run("set-floor", "150")
            self.assertEqual(env.floor(), 100)
        finally:
            env.cleanup()
    def test_invalide(self):
        env = FakeEnv()
        try:
            self.assertNotEqual(env.run("set-floor", "abc").returncode, 0)
            self.assertNotEqual(env.run("set-floor").returncode, 0)
        finally:
            env.cleanup()
class TestMode(unittest.TestCase):
    """S8: mode signals."""
    def test_signaux(self):
        for mode, sig in [("game", "SIGUSR1"), ("silent", "SIGUSR2"),
                           ("free", "SIGWINCH")]:
            env = FakeEnv()
            try:
                r = env.run("mode", mode)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f"--user kill --signal={sig} coolingctl.service",
                              env.systemctl_calls())
            finally:
                env.cleanup()
    def test_mode_invalide(self):
        env = FakeEnv()
        try:
            self.assertNotEqual(env.run("mode", "nimporte").returncode, 0)
        finally:
            env.cleanup()
if __name__ == "__main__":
    unittest.main()
