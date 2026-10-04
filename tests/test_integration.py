#!/usr/bin/env python3
"""Tests d'intégration contre le daemon LIVE (service user coolingctl).

Sautés si le daemon n'est pas en cours d'exécution (CI sans machine).

Specs couvertes :
  S9  le fichier d'état est publié et schema-valide en continu
  S10 bascule mode par signaux sans restart (NRestarts inchangé)
  S11 plateau modifié à chaud sans restart du daemon
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
    "coolingctl", "gaming-plateau.json")
KEYS = {"mode", "temp", "plateau_pct", "plateau_rpm",
        "rpm_cmd", "rpm_reported", "pad_present"}


def daemon_actif():
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "coolingctl"],
                           capture_output=True, text=True)
        return r.stdout.strip() == "active" and os.path.exists(STATUS_FILE)
    except OSError:
        return False


def lire_status():
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


def attendre(predicate, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.5)
    return False


@unittest.skipUnless(daemon_actif(), "daemon coolingctl non actif")
class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.etat_initial = lire_status()
        cls.plateau_initial = cls._lire_plateau()

    @classmethod
    def tearDownClass(cls):
        # restauration complete de l'etat initial
        plateau = cls.plateau_initial
        with open(GAMING_JSON) as f:
            contenu = f.read()
        with open(GAMING_JSON, "w") as f:
            f.write(re.sub(r'"percent": *[0-9]*', f'"percent": {plateau}', contenu))
        signal_daemon("SIGHUP")  # resynchroniser le daemon avec le fichier restaure
        mode = cls.etat_initial["mode"]
        sig = {"jeu": "SIGUSR1", "courbe": "SIGUSR2", "libre": "SIGWINCH"}[mode]
        signal_daemon(sig)

    @staticmethod
    def _lire_plateau():
        with open(GAMING_JSON) as f:
            contenu = f.read()
        m = re.search(r'"percent": *([0-9]+)', contenu)
        return int(m.group(1))

    @staticmethod
    def _nrestarts():
        r = subprocess.run(["systemctl", "--user", "show", "coolingctl",
                            "-p", "NRestarts"], capture_output=True, text=True)
        return int(r.stdout.strip().split("=")[1])

    def test_s9_schema_status(self):
        fields = lire_status()
        self.assertTrue(KEYS.issubset(fields), fields)
        self.assertIn(fields["mode"], {"courbe", "jeu", "libre"})
        float(fields["temp"])
        float(fields["plateau_pct"])
        int(fields["rpm_cmd"])
        int(fields["rpm_reported"])
        self.assertIn(fields["pad_present"], {"0", "1"})

    def test_s10_bascule_mode_sans_restart(self):
        n0 = self._nrestarts()
        signal_daemon("SIGUSR1")
        self.assertTrue(attendre(lambda: lire_status()["mode"] == "jeu"),
                        "mode jeu non atteint")
        signal_daemon("SIGUSR2")
        self.assertTrue(attendre(lambda: lire_status()["mode"] == "courbe"),
                        "mode courbe non atteint")
        self.assertEqual(self._nrestarts(), n0, "le daemon a redémarré !")

    def test_s11_plateau_a_chaud(self):
        n0 = self._nrestarts()
        with open(GAMING_JSON) as f:
            contenu = f.read()
        with open(GAMING_JSON, "w") as f:
            f.write(re.sub(r'"percent": *[0-9]*', '"percent": 33', contenu))
        signal_daemon("SIGHUP")
        self.assertTrue(
            attendre(lambda: lire_status()["plateau_rpm"] == "1400"),
            f"plateau_rpm={lire_status().get('plateau_rpm')} != 1400")
        self.assertEqual(self._nrestarts(), n0, "le daemon a redémarré !")


if __name__ == "__main__":
    unittest.main()
