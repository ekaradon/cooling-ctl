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
  S36 the full view exposes the LED selector: ComboBox over the effects,
      brightness slider, static picker (swatches + hue/saturation), all
      wired through the helper
  S31 the compact cat must be rendered as a Kirigami.Icon isMask tinted
      Kirigami.Theme.textColor — KSvg does not recolor symbolic SVGs outside
      an applet context (lived bug: dark-on-dark cat, invisible in dark theme)
  S41 the brightness slider must not be driven by a conditional
      `Binding on value` — when the `when` clause goes false (ledBusy latch),
      QML RESTORES the pre-binding value (the slider default 0): the thumb
      flashed to 0 % on every effect change. Imperative resync only
      (Connections + Timer), the floor slider's pattern
  S42 a lock Timer may only RELEASE its flag — modeLock's onTriggered
      re-set modeBusy = true: the optimistic lock latched forever after the
      first mode commit and the mode never resynced from the daemon again
  S48 workflow files must parse as YAML — an invalid one fails every run
      at load time (zero jobs created, 0 s failure in the run list) and
      GitHub surfaces it nowhere else. Lived bug: the unquoted `if:` of
      the package job contained "chore(release): v" and the release bot
      silently never opened its chore(release) PR after any merge
  S49 the package job must publish a GitHub Release — a tag alone never
      showed in the Releases tab (the repo had none at all); the release
      is created from the CHANGELOG section and the built .pkg.tar.zst
      is attached to it
"""
import os
import re
import stat
import unittest

import yaml

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
        self.assertNotIn("floorFromFraction", self.qml,
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
        block = self.qml.split("id: floorSlider", 1)[1].split("Timer {", 1)[0]
        self.assertIn("onPressedChanged:", block,
                      "slider release goes through onPressedChanged")
        self.assertNotIn("onPressed:", block,
                         "QQC2 Slider: pressed is a property, not a signal")
        self.assertNotIn("onReleased:", block,
                         "QQC2 Slider: the released() signal does not exist")
        self.assertIn("onMoved:", block,
                      "wheel/keyboard: moved() outside a drag must commit")

    def test_s31_chat_visible_en_theme_sombre(self):
        """Lived bug 2026-10-04: the compact cat (a symbolic SVG with
        fill:currentColor and the Breeze LIGHT text color baked into the
        file) rendered dark-on-dark and was invisible in the dark theme —
        KSvg does not recolor symbolic SVGs outside of an applet context.
        The cat must be a Kirigami.Icon mask tinted with the theme text
        color, so it adapts to dark and light alike."""
        parts = self.qml.split("id: catItem")
        self.assertGreaterEqual(len(parts), 2, "the cat must exist (id catItem)")
        cat = parts[1][:1200]
        self.assertIn("isMask: true", cat, "the cat must render as a mask")
        self.assertIn("color: Kirigami.Theme.textColor", cat,
                      "the cat must be tinted with the theme text color")
        self.assertNotIn("KSvg.SvgItem", self.qml,
                         "KSvg does not recolor symbolic SVGs here")

    def test_s39_pad_fan_label(self):
        """The pad readout is labeled "Pad fan" — the RPM number alone
        was ambiguous next to the laptop fans readout (user request)."""
        self.assertIn('text: i18n("Pad fan")', self.qml,
                      "the pad RPM readout must say Pad fan")
        self.assertNotIn('text: i18n("Pad")', self.qml,
                         "the bare Pad label must not resurface")

    def test_s40_led_controls_gated_until_known(self):
        """No control shows a value we don't have: the effect combo and the
        brightness slider stay disabled until the daemon's configured state
        arrives (first poll), and the % label shows an ellipsis instead of
        a fake "0 %" (lived complaint: 0 % flashed before 40 %)."""
        self.assertIn("enabled: root.polls > 0", self.qml,
                      "the effect ComboBox must be disabled before the first poll")
        self.assertIn("enabled: root.ledBright >= 0", self.qml,
                      "the brightness slider must be disabled until the brightness is known")
        self.assertIn('i18n("…")', self.qml,
                      "unknown brightness must show an ellipsis, never a fake value")

    def test_s36_led_ui(self):
        """The full view must not become a wall of controls: LED settings
        live in a second tab (media-player plasmoid pattern). The Lighting
        page carries the effect ComboBox, the brightness slider and the
        static color picker, all wired through the helper."""
        self.assertIn("PlasmaComponents.TabBar {", self.qml,
                      "the full view must be tabbed (cooling / lighting)")
        self.assertIn('text: i18n("Cooling")', self.qml)
        self.assertIn('text: i18n("Lighting")', self.qml)
        self.assertIn("mainTabs.currentIndex === 0", self.qml,
                      "the cooling page must bind to the first tab")
        self.assertIn("mainTabs.currentIndex === 1", self.qml,
                      "the lighting page must bind to the second tab")
        self.assertIn('values: ["keep", "off", "static", "spectrum", "wave", "heat"]',
                      self.qml, "the ComboBox must cover all supported effects")
        self.assertIn('" led bright "', self.qml,
                      "the brightness slider must commit via the helper")
        self.assertIn('" led static "', self.qml,
                      "the color button must commit via the helper")
        self.assertIn('root.led === "static"', self.qml,
                      "the static color picker must only show for static")
        self.assertIn('root.led !== "keep" && root.led !== "heat"', self.qml,
                      "the brightness slider must hide for stock AND heat")

    def test_s37_optimistic_updates(self):
        """Lived annoyance: after a mode/effect change, the UI waited for
        the daemon round-trip (~2-5 s) before showing anything. Every
        commit must be OPTIMISTIC: apply locally, lock the poll out 4 s,
        resync on release; a BusyIndicator in the tab bar marks pending
        application."""
        self.assertIn("function commitMode(", self.qml,
                      "mode switches must commit optimistically")
        self.assertIn("root.modeBusy = true", self.qml,
                      "a mode commit must hold the poll lock")
        self.assertIn("if (!root.modeBusy)", self.qml,
                      "the poll must respect the mode lock")
        self.assertIn("if (!root.ledBusy)", self.qml,
                      "the poll must respect the lighting lock")
        self.assertIn("root.led = values[index]", self.qml,
                      "the effect ComboBox must apply optimistically")
        self.assertIn("PlasmaComponents.BusyIndicator", self.qml,
                      "pending application must be visible (spinner)")
        self.assertIn("visible: root.modeBusy || root.ledBusy || root.sliderBusy",
                      self.qml, "the spinner covers every pending commit")

    def test_s27_slider_resilient(self):
        """The floor label shows the step (snapFloor) and the slider
        periodically resynchronizes (anti-desync after a failed drag)."""
        self.assertIn("CLogic.snapFloor(500 + root.floor * 27)", self.qml,
                      "the resting label must show the step, not the raw computation")
        self.assertGreaterEqual(self.qml.count("floorSlider.value = 500 + root.floor * 27"), 2,
                                "a resync mechanism is needed beyond onFloorChanged")

    def test_s41_brightness_slider_sans_binding_conditionnel(self):
        """Lived bug 2026-10-05: the brightness thumb flashed to 0 % on
        every effect change, then came back to the real value ~4 s later.
        The slider value was driven by a conditional `Binding on value`:
        when an effect commit latched ledBusy, the `when` clause went
        false and QML RESTORED the value the property had before the
        binding activated — the slider's default 0. The binding only
        reactivated when the lock released. Imperative resync only
        (Connections + resync Timer), exactly the floor slider's
        pattern, which never had the bug."""
        self.assertNotIn("Binding on value", self.qml,
                         "a conditional Binding restores the pre-binding "
                         "value when it deactivates — resync imperatively")
        self.assertGreaterEqual(self.qml.count("ledBrightness.value = root.ledBright"), 2,
                                "the brightness slider needs a resync beyond "
                                "onLedBrightChanged (failed commits)")

    def test_s42_les_locks_se_relachent(self):
        """Lived bug: modeLock's onTriggered re-set modeBusy = true —
        after the first mode commit the optimistic lock latched forever,
        the poll stopped updating root.mode and a failed commit would
        have left the UI lying indefinitely. A lock Timer RELEASES its
        flag; latching it is commit code, not release code."""
        self.assertEqual(re.findall(r"onTriggered:[^\n]*Busy = true", self.qml), [],
                         "a lock Timer must release its flag, never latch it")
        self.assertIn("onTriggered: root.modeBusy = false", self.qml,
                      "modeLock must release modeBusy after its 4 s hold")


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


class TestStructureWorkflows(unittest.TestCase):
    def test_s48_workflows_parse(self):
        """Lived bug: an unquoted `if:` value containing "chore(release): v"
        made release.yml unparseable — every push to main failed the
        workflow at load time (zero jobs, 0 s) and the release bot never
        opened its chore(release) PR. GitHub's only signal is a failed
        run with no jobs, which looks like noise in the list."""
        workflows = os.path.join(ROOT, ".github", "workflows")
        for name in sorted(os.listdir(workflows)):
            if not name.endswith((".yml", ".yaml")):
                continue
            with self.subTest(workflow=name):
                with open(os.path.join(workflows, name)) as f:
                    yaml.safe_load(f)


class TestStructureReleaseWorkflow(unittest.TestCase):
    """S49: the package job publishes a GitHub Release, not just a tag."""

    def setUp(self):
        with open(os.path.join(ROOT, ".github", "workflows",
                              "release.yml")) as f:
            self.release = f.read()

    def test_s49_publishes_a_github_release(self):
        self.assertIn("gh release create", self.release,
                      "a tag alone never shows in the Releases tab")
        self.assertIn("gh release upload", self.release,
                      "the built package must be attached to the release")
        self.assertIn("GH_TOKEN", self.release,
                      "gh needs the token to write the release")


if __name__ == "__main__":
    unittest.main()
