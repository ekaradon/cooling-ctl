#!/usr/bin/env python3
"""Tests structurels anti-régression — chaque règle encode un bug vécu.

Leçon du 2026-10-04 : les bugs QML d'un plasmoid sont silencieux à l'exécution
(propriétés attachées inexistantes, absence de hints Layout, modes 600 dans le
paquet). Ces vérifications statiques les attrapent avant l'installation.

  S19 `expanded` doit être basculé via le PlasmoidItem (root.expanded),
      jamais via l'objet attaché `Plasmoid` — piége de migration Plasma 5→6 :
      `Plasmoid.expanded` n'existe pas (AppletQuickItem.expanded si)
  S20 le compact doit déclarer ses hints de taille via Layout.* —
      le conteneur de panneau lit Layout.*, pas les tailles implicites
  S21 le compact doit se déclarer bouton (Accessible.role: Button)
      et gérer son clic (MouseArea) — le shell ne le fait pas pour nous
  S22 preferredRepresentation doit être le compact (sinon popupHS)
  S23 aucun debug (console.log) ne doit rester dans les sources QML
  S24 les fichiers des sources doivent être lisibles par tous (644/755) —
      un paquet copie les modes, le bug 600 a rendu le widget invisible
  S30 le slider ne doit pas utiliser onPressed:/onReleased: — QQC2 Slider
      n'expose pas ces signaux (pressed est une propriété) : le handler
      inexistant fait tomber le plasmoid ENTIER en fallback icône settings,
      et qmllint ne le voit pas (handler muet par UnqualifiedAccess=disable)
"""
import os
import stat
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QML = os.path.join(ROOT, "plasmoid", "org.coolingctl",
                   "contents", "ui", "main.qml")
HELPER = os.path.join(ROOT, "plasmoid", "org.coolingctl",
                      "contents", "code", "coolingctl.sh")


class TestStructureQml(unittest.TestCase):
    def setUp(self):
        with open(QML) as f:
            self.qml = f.read()

    def test_s19_expanded_sur_plasmoiditem(self):
        """Le toggle expanded doit passer par root (PlasmoidItem/AppletQuickItem)."""
        self.assertNotIn("Plasmoid.expanded", self.qml,
                         "Plasmoid.expanded n'existe pas en Plasma 6 "
                         "(expanded vit sur AppletQuickItem)")
        self.assertGreaterEqual(self.qml.count("root.expanded"), 3,
                                "bascule expanded absente du compact")

    def test_s20_hints_layout_du_compact(self):
        """Le conteneur de panneau dimensionne via Layout.*, pas implicit*."""
        self.assertIn("Layout.preferredWidth: vertical ? -1 : compactRow.implicitWidth",
                      self.qml)
        self.assertIn("Layout.minimumWidth: compactRow.implicitWidth", self.qml)

    def test_s21_compact_est_un_bouton(self):
        self.assertIn("Accessible.role: Accessible.Button", self.qml)
        self.assertIn("MouseArea {", self.qml)

    def test_s22_preferred_representation(self):
        self.assertIn("preferredRepresentation: compactRepresentation", self.qml)

    def test_s23_aucun_debug(self):
        self.assertNotIn("console.log", self.qml)

    def test_s28_slider_snap_pendant_drag(self):
        """Le handle doit crantifier pendant le drag. Solution native QQC2 :
        snapMode SnapAlways (pattern du slider Animation speed de la landing
        page Plasma, kcms/landingpage) — la position snape sur la grille des
        pas a chaque mouvement. Le default du wrapper Plasma est SnapOnRelease
        (glissement continu puis snap au relachement), d'ou la surcharge
        obligatoire. Pas de drag custom : interactive: false + MouseArea est
        un hack a proscrire (casse la molette, faux positif qmllint sur
        interactive, comportement non standard)."""
        self.assertIn("snapMode: QQC2.Slider.SnapAlways", self.qml,
                      "le snap natif du handle doit etre explicite "
                      "(le default Plasma est SnapOnRelease)")
        self.assertNotIn("interactive: false", self.qml,
                         "le drag interne du slider ne doit pas etre desactive")
        self.assertNotIn("plateauFromFraction", self.qml,
                         "le drag custom a ete remplace par snapMode SnapAlways")
        self.assertIn('visible: root.padVisible && root.mode !== "libre" && root.polls > 0', self.qml,
                      "le slider ne doit pas apparaitre avant la premiere donnee")

    def test_s30_handlers_valides_du_slider(self):
        """Bug vécu 2026-10-04 : « Cannot assign to non-existent property
        "onReleased" » au clic — le plasmoid entier partait en fallback icône
        settings. QQC2 Slider n'a pas de signaux pressed()/released() : pressed
        est une propriété. Le release se branche sur onPressedChanged, le
        drag/molette/clavier sur moved(). qmllint rate cette classe d'erreur
        (le warning « no matching signal found for handler » est catégorisé
        [unqualified], muetté par UnqualifiedAccess=disable du .qmllint.ini)."""
        block = self.qml.split("id: plateauSlider", 1)[1].split("Timer {", 1)[0]
        self.assertIn("onPressedChanged:", block,
                      "le release du slider passe par onPressedChanged")
        self.assertNotIn("onPressed:", block,
                         "Slider QQC2 : pressed est une propriété, pas un signal")
        self.assertNotIn("onReleased:", block,
                         "Slider QQC2 : le signal released() n'existe pas")
        self.assertIn("onMoved:", block,
                      "molette/clavier : moved() hors drag doit committer")

    def test_s27_slider_resilient(self):
        """Le plateau affiche le palier (snapPlateau) et le slider
        se resynchronise periodiquement (anti-desync apres drag rate)."""
        self.assertIn("CLogic.snapPlateau(500 + root.plateau * 27)", self.qml,
                      "le label au repos doit afficher le palier, pas le calcul brut")
        self.assertGreaterEqual(self.qml.count("plateauSlider.value = 500 + root.plateau * 27"), 2,
                                "il faut un mecanisme de resync en plus du onPlateauChanged")


class TestStructureSources(unittest.TestCase):
    def test_s24_modes_des_sources(self):
        """644 partout, 755 pour le helper — le paquet copie ces modes."""
        plasmoid_dir = os.path.join(ROOT, "plasmoid", "org.coolingctl")
        for dirpath, _, files in os.walk(plasmoid_dir):
            for name in files:
                path = os.path.join(dirpath, name)
                mode = stat.S_IMODE(os.stat(path).st_mode)
                if path == HELPER:
                    self.assertTrue(mode & stat.S_IXUSR, f"{name} doit etre executable")
                else:
                    self.assertEqual(mode & 0o777, 0o644,
                                     f"{name} doit etre 644 (est {oct(mode)})")


if __name__ == "__main__":
    unittest.main()
