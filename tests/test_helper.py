#!/usr/bin/env python3
"""Tests of the coolingctl.sh helper — the plasmoid's interface contract.

Covered specs:
  S6  `status` : ligne à 9 champs tctl|fan1|fan2|pad_rpm|mode|plateau_pct|gpu|cpu|gpu_pct
      mode passthrough: silent|game|free (fallback silent);
      pad_rpm and plateau come from the state file; absent -> -1
  S7  `set-plateau N`: writes the plateau into the json (clamped 0..100),
      bounded, invalid rejected; sends SIGHUP to the daemon
  S8  `mode X`: SIGUSR1 (game), SIGUSR2 (silent), SIGWINCH (free);
      invalid mode rejected

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
        self.gaming_json = os.path.join(self.tmp, "gaming-plateau.json")
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
        e["COOLINGCTL_DRM_DIR"] = self.drm
        e.pop("LD_LIBRARY_PATH", None)
        return e

    def env_par_defaut(self):
        """Environment WITHOUT overrides: the helper must resolve
        XDG_CONFIG_HOME/coolingctl/gaming-plateau.json on its own."""
        e = self.env
        e.pop("COOLINGCTL_GAMING_JSON")
        return e

    def run_par_defaut(self, *args):
        return subprocess.run(["sh", HELPER, *args], env=self.env_par_defaut(),
                              capture_output=True, text=True, timeout=10)

    def run(self, *args):
        return subprocess.run(["sh", HELPER, *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def plateau(self):
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
        env = FakeEnv("mode=silent\ntemp=60.0\nplateau_pct=30.0\n"
                      "plateau_rpm=1300\nrpm_cmd=500\nrpm_reported=500\npad_present=1\n")
        try:
            r = env.run("status")
            self.assertEqual(r.returncode, 0, r.stderr)
            champs = r.stdout.strip().split("|")
            self.assertEqual(len(champs), 9, champs)
            self.assertEqual(champs[3], "500")        # pad_rpm
            self.assertEqual(champs[4], "silent")  # curve -> silent
            self.assertEqual(champs[5], "30.0")        # plateau
            self.assertRegex(champs[7], r"^[0-9]+$")    # charge CPU 0..100
            self.assertRegex(champs[8], r"^-?[0-9]+$")  # charge GPU (-1 si absente)
        finally:
            env.cleanup()

    def test_mode_game_and_free(self):
        for mode, attendu in [("game", "game"), ("free", "free")]:
            env = FakeEnv(f"mode={mode}\nrpm_reported=1300\nplateau_pct=30\n")
            try:
                champs = env.run("status").stdout.strip().split("|")
                self.assertEqual(champs[4], attendu)
            finally:
                env.cleanup()

    def test_status_absent(self):
        env = FakeEnv()  # pas de fichier d'état
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
        XDG_CONFIG_HOME/coolingctl/gaming-plateau.json (canonical names)."""
        env = FakeEnv()
        try:
            canonique = os.path.join(env.env["XDG_CONFIG_HOME"],
                                     "coolingctl", "gaming-plateau.json")
            # an existing installation: the config file is already there
            shutil.copy(env.gaming_json, canonique)
            r = env.run_par_defaut("set-plateau", "25")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(canonique),
                            f"the helper did not resolve the default path: {canonique}")
            with open(canonique) as f:
                self.assertIn('"percent": 25', f.read())
        finally:
            env.cleanup()


class TestSetPlateau(unittest.TestCase):
    """S7: plateau write + SIGHUP."""

    def test_ecriture_et_signal(self):
        env = FakeEnv()
        try:
            r = env.run("set-plateau", "40")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(env.plateau(), 40)
            self.assertIn("--user kill --signal=SIGHUP coolingctl.service",
                          env.systemctl_calls())
        finally:
            env.cleanup()

    def test_clamp(self):
        env = FakeEnv()
        try:
            env.run("set-plateau", "2")
            self.assertEqual(env.plateau(), 2)   # 0..100 valide : plus de clamp a 5
            self.assertEqual(env.run("set-plateau", "0").returncode, 0)
            self.assertEqual(env.plateau(), 0)   # plancher 0 % = 500 RPM
            self.assertNotEqual(env.run("set-plateau", "-3").returncode, 0)  # non numerique : rejete
            env.run("set-plateau", "150")
            self.assertEqual(env.plateau(), 100)
        finally:
            env.cleanup()

    def test_invalide(self):
        env = FakeEnv()
        try:
            self.assertNotEqual(env.run("set-plateau", "abc").returncode, 0)
            self.assertNotEqual(env.run("set-plateau").returncode, 0)
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
