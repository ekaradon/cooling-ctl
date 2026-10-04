# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.1] — 2026-10-04

- Config self-provisioning: the daemon creates `~/config/coolingctl/`
  with sensible defaults on first start (nothing to write before the first
  run); existing files are never overwritten. Guarded by S32.
- `game-floor.json` is now a single-point curve (the first point IS the
  floor); the README example drops the confusing 120 °C padding point.

## [0.5.0] — 2026-10-04

- "Plateau" vocabulary retired in favor of "floor" everywhere: config file
  is now `game-floor.json`, status fields are `floor_pct`/`floor_rpm`, the
  CLI verb is `set-floor`. Breaking: rename your config file (fields
  unchanged).
- README rewritten, much shorter: what it does, install, setup, credits —
  details live in AGENTS.md.

## [0.4.1] — 2026-10-04

- Fix: the compact cat was invisible in the dark theme — KSvg does not
  recolor symbolic SVGs outside an applet context. It now renders as a
  Kirigami.Icon mask tinted with the theme text color (dark and light
  verified), guarded by structural test S31.
- AGENTS.md: crash trap (never deploy a .local copy under a live panel id),
  screenshot pipeline documented.
- Compact screenshots regenerated with the fix.

## [0.4.0] — 2026-10-04

- **English protocol**: the daemon now publishes `mode=silent|game|free` in the
  status file (was `courbe|jeu|libre`), and the helper CLI verbs are
  `game|silent|free` (was `jeu|silencieux|libre`); the helper passes the mode
  through instead of requalifying it. Breaking: the plasmoid, helper and
  daemon must be upgraded together (same package).
- All comments, docstrings, UI strings and tool output translated to English;
  UI labels anglicized ("Laptop fans", "SILENT CURVE", "GAME MODE", …).
- Screenshots added (dark/light, compact and full views), generated via the
  capture pipeline.

## [0.3.1] — 2026-10-04

- Package renamed `fw16-coolingctl` → `cooling-ctl` to match the repository
  name (the project is not Framework-16-specific). Daemon path moves to
  `/usr/lib/cooling-ctl/`, systemd unit and plasmoid id unchanged.
  `replaces=(fw16-coolingctl)` migrates existing installs.
- PKGBUILD now builds from the published git tag (`source` git + `#tag=`),
  making it AUR-ready.

## [0.3.0] — 2026-10-04

First public release.

- Daemon `coolingctld`: exclusive owner of the pad's HID interface, silent
  curve against k10temp, fixed gaming plateau, free (firmware) mode, mode
  switching via POSIX signals without restarts, hot config reload (`SIGHUP`),
  atomic status file, automatic reconnection when the pad is absent.
- Plasma 6 plasmoid `org.coolingctl`: hero temperatures with rolling averages,
  4-series chart (CPU/GPU temps, internal fans, pad RPM) with anti-collision
  labels and threshold band, pad control and game mode switches, stepped
  RPM slider (500→3200, 300 RPM steps, snapped handle, self-resyncing).
- Compact panel view: rolling-average CPU/GPU temperatures, per-component
  load, animated cat paced by the load (frames from CatWalk, art lineage
  RunCat).
- Helper `coolingctl.sh`: machine-readable `status` (9 fields),
  `set-plateau`, `mode`.
- udev rule for unprivileged pad access, user systemd unit.
- Test suite: unit, structural (regression-encoded), integration, QML logic
  via qmltestrunner, qmllint; optional HID protocol parity against the
  reference controller (`COOLINGCTL_REFERENCE`).
