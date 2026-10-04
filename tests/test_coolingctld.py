#!/usr/bin/env python3
"""Tests unitaires du daemon coolingctld — spécifications fonctionnelles du projet.

Specs couvertes :
  S1  protocole HID identique octet par octet au contrôleur de référence
  S2  conversion % -> RPM : 500 + pct*27, paliers de 50, clamp [0, 100]
  S3  interpolation linéaire de la courbe (bornes = points extrêmes)
  S4  lecture des courbes JSON (courbe triée, plateau = premier point)
  S5  fichier d'état key=valeur, champs complets, écriture atomique
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(ROOT, "daemon", "coolingctld.py")
# Controleur de reference (protocole HID historique) : chemin fourni par
# COOLINGCTL_REFERENCE (ex. un clone de razer-coolingpad-linux contenant
# razer-coolingpad-fancurve.py). Absent -> les tests de parite S1 sont
# sautes, tout le reste de la suite reste actif.
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
                     "controleur de reference absent (COOLINGCTL_REFERENCE)")
class TestProtocoleHID(unittest.TestCase):
    """S1 : rapports HID en parité octet par octet avec la référence."""

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
    """S2 : mapping % -> RPM."""

    def test_mapping_connu(self):
        cases = {0: 500, 30: 1300, 37: 1500, 50: 1850, 100: 3200}
        for pct, rpm in cases.items():
            self.assertEqual(d.pct_to_rpm(pct), rpm, f"pct {pct}")

    @unittest.skipUnless(ref is not None,
                         "controleur de reference absent (COOLINGCTL_REFERENCE)")
    def test_parity_reference(self):
        for pct in range(0, 101, 7):
            self.assertEqual(d.pct_to_rpm(pct), ref.percent_to_rpm(pct))

    def test_clamp(self):
        self.assertEqual(d.pct_to_rpm(-5), 500)
        self.assertEqual(d.pct_to_rpm(150), 3200)


class TestInterpolation(unittest.TestCase):
    """S3 : interpolation de courbe."""

    CURVE = [(0, 0), (76, 0), (82, 20), (85, 35), (88, 55), (92, 75), (95, 90), (98, 100)]

    def test_sous_premier_point(self):
        self.assertEqual(d.interpolate(self.CURVE, -10), 0)

    def test_au_dernier_point(self):
        self.assertEqual(d.interpolate(self.CURVE, 200), 100)

    def test_entre_points(self):
        self.assertAlmostEqual(d.interpolate(self.CURVE, 79), 10.0)

    def test_point_exact(self):
        self.assertEqual(d.interpolate(self.CURVE, 85), 35)

    def test_courbe_vide(self):
        self.assertIsNone(d.interpolate([], 50))


class TestConfig(unittest.TestCase):
    """S4 : lecture des JSON de courbes."""

    def test_load_curve_triee(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"curve": [{"temp": 120, "percent": 30},
                                 {"temp": 0, "percent": 30}]}, f)
            path = f.name
        try:
            self.assertEqual(d.State.load_curve(path), [(0, 30.0), (120, 30.0)])
        finally:
            os.unlink(path)

    def test_load_plateau(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"curve": [{"temp": 0, "percent": 30},
                                 {"temp": 120, "percent": 30}]}, f)
            path = f.name
        try:
            self.assertEqual(d.State.load_plateau(path), 30.0)
        finally:
            os.unlink(path)

    def test_fichiers_absents(self):
        self.assertEqual(d.State.load_curve("/inexistant.json"), [])
        self.assertIsNone(d.State.load_plateau("/inexistant.json"))


class TestStatusFile(unittest.TestCase):
    """S5 : fichier d'état key=valeur, complet, atomique."""

    def _write(self, **kw):
        tmpdir = tempfile.mkdtemp()
        d.STATUS_FILE = os.path.join(tmpdir, "coolingctl.status")
        defaults = dict(mode="jeu", temp=63.5, plateau_pct=30.0,
                        rpm_cmd=1300, rpm_rep=1300, pad_present=True)
        defaults.update(kw)
        d.write_status(**defaults)
        with open(d.STATUS_FILE) as f:
            content = f.read()
        return tmpdir, content

    def test_format_complet(self):
        tmpdir, content = self._write()
        try:
            for attendu in ["mode=jeu", "temp=63.5", "plateau_pct=30.0",
                           "plateau_rpm=1300", "rpm_cmd=1300",
                           "rpm_reported=1300", "pad_present=1"]:
                self.assertIn(attendu, content)
            self.assertNotIn(".tmp", os.listdir(tmpdir))  # atomicité
        finally:
            shutil.rmtree(tmpdir)

    def test_valeurs_absentes(self):
        tmpdir, content = self._write(mode="courbe", temp=None,
                                      rpm_cmd=None, rpm_rep=None, pad_present=False)
        try:
            for attendu in ["temp=-1", "rpm_cmd=-1", "rpm_reported=-1", "pad_present=0"]:
                self.assertIn(attendu, content)
        finally:
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
