#!/usr/bin/env python3
"""Structural anti-regression tests — every rule encodes a bug we actually hit.

Lesson of 2026-10-04: a plasmoid's QML bugs are silent at runtime
(non-existent attached properties, missing Layout hints, 600 modes in the
package). These static checks catch them before installation.

  S19 `expanded` must be toggled through the PlasmoidItem (root.expanded),
      never through the attached `Plasmoid` object — a Plasma 5 to 6 migration trap:
      `Plasmoid.expanded` does not exist (AppletQuickItem.expanded does)
  S20 the compact must declare its size hints via Layout.* —
      the panel container reads Layout.*, not implicit sizes
  S21 the compact must declare itself a button (Accessible.role: Button)
      and handle its click (MouseArea) — the shell does not do it for us
  S22 preferredRepresentation must be the compact (else popupHS)
  S23 no debug (console.log) must remain in the QML sources
  S24 source files must be readable by everyone (644/755) —
      a package copies modes, the 600-mode bug made the widget invisible
  S30 the slider must not use onPressed:/onReleased: — the QQC2 Slider
      does not expose those signals (pressed is a property): a handler
      on a non-existent one takes the WHOLE plasmoid down to a settings icon,
      and qmllint does not see it (handler muted by UnqualifiedAccess=disable)
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
        """The expanded toggle must go through root (PlasmoidItem/AppletQuickItem)."""
        self.assertNotIn("Plasmoid.expanded", self.qml,
                         "Plasmoid.expanded does not exist in Plasma 6 "
                         "(expanded lives on AppletQuickItem)")
        self.assertGreaterEqual(self.qml.count("root.expanded"), 3,
                                "compact missing the expanded toggle")

    def test_s20_hints_layout_du_compact(self):
        """The panel container sizes via Layout.*, not implicit*."""
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
        """The handle must snap during the drag. Native QQC2 solution:
        snapMode SnapAlways (the pattern of Plasma's landing page Animation
        speed slider, kcms/landingpage) — the position snaps onto the step grid
        on every move. The Plasma wrapper default is SnapOnRelease
        (continuous slide then snap on release), hence the mandatory
        override. No custom drag: interactive: false + MouseArea is
        a hack to avoid (breaks the wheel, qmllint false positive on
        interactive, non-standard behavior)."""
        self.assertIn("snapMode: QQC2.Slider.SnapAlways", self.qml,
                      "the native handle snap must be explicit "
                      "(the Plasma default is SnapOnRelease)")
        self.assertNotIn("interactive: false", self.qml,
                         "the slider's internal drag must not be disabled")
        self.assertNotIn("plateauFromFraction", self.qml,
                         "the custom drag was replaced by snapMode SnapAlways")
        self.assertIn('visible: root.padVisible && root.mode !== "free" && root.polls > 0', self.qml,
                      "the slider must not appear before the first data point")

    def test_s30_handlers_valides_du_slider(self):
        """Lived bug 2026-10-04: "Cannot assign to non-existent property
        "onReleased" on click — the whole plasmoid fell back to a settings
        icon. QQC2 Slider has no pressed()/released() signals: pressed
        is a property. Release hooks into onPressedChanged, drag/wheel/
        keyboard into moved(). qmllint misses this class of error
        ("no matching signal found for handler" is categorized
        [unqualified], muted by UnqualifiedAccess=disable in .qmllint.ini)."""
        block = self.qml.split("id: plateauSlider", 1)[1].split("Timer {", 1)[0]
        self.assertIn("onPressedChanged:", block,
                      "slider release goes through onPressedChanged")
        self.assertNotIn("onPressed:", block,
                         "QQC2 Slider: pressed is a property, not a signal")
        self.assertNotIn("onReleased:", block,
                         "QQC2 Slider: the released() signal does not exist")
        self.assertIn("onMoved:", block,
                      "wheel/keyboard: moved() outside a drag must commit")

    def test_s27_slider_resilient(self):
        """The plateau label shows the step (snapPlateau) and the slider
        periodically resynchronizes (anti-desync after a failed drag)."""
        self.assertIn("CLogic.snapPlateau(500 + root.plateau * 27)", self.qml,
                      "the resting label must show the step, not the raw computation")
        self.assertGreaterEqual(self.qml.count("plateauSlider.value = 500 + root.plateau * 27"), 2,
                                "a resync mechanism is needed beyond onPlateauChanged")


class TestStructureSources(unittest.TestCase):
    def test_s24_modes_des_sources(self):
        """644 everywhere, 755 for the helper — the package copies these modes."""
        plasmoid_dir = os.path.join(ROOT, "plasmoid", "org.coolingctl")
        for dirpath, _, files in os.walk(plasmoid_dir):
            for name in files:
                path = os.path.join(dirpath, name)
                mode = stat.S_IMODE(os.stat(path).st_mode)
                if path == HELPER:
                    self.assertTrue(mode & stat.S_IXUSR, f"{name} doit etre executable")
                else:
                    self.assertEqual(mode & 0o777, 0o644,
                                     f"{name} must be 644 (is {oct(mode)})")


if __name__ == "__main__":
    unittest.main()
