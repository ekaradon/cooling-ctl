# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.7.0] - 2026-10-05

### Added
- publish a GitHub Release with notes and the package asset - `feat(release)` (a692a6e)
- automated release flow - prepare job opens release PRs, package job tags and builds - `feat(release)` (081b426)
- prepare-release tool - version, changelog and PKGBUILD bumps from conventional commits - `feat(release)` (fd2860c)

### Fixed
- quote the package job if — unparseable release.yml stopped all releases - `fix(ci)` (7e44ef8)
- release the mode lock when its timer fires - `fix(plasmoid)` (b69af1a)
- keep the LED brightness steady while an effect commit is pending - `fix(plasmoid)` (8e26a0f)

## [0.6.2] — 2026-10-05

- Static typing for the daemon: full PEP 484 annotations, `mypy.ini`
  (every def annotated, explicit Optional, no unchecked Any returned from
  JSON payloads), wired into `tests/run.sh` (skipped when mypy is absent,
  `MYPY=` provides an arbitrary binary). `State.last_frame` becomes a
  declared attribute (the defensive getattr retires); `cfg_num`/`cfg_str`
  narrow the config dicts.
- qmllint's `UnqualifiedAccess` re-enabled: it is the category that
  catches handlers on non-existent signals (the lived `onRejected` bug
  that killed the whole widget). The known Plasma false positives
  (the `i18n()` global, `root` inside the representations) are
  suppressed line-by-line in `main.qml` — the rule stays armed.

## [0.6.1] — 2026-10-05

- Fix: LED controls never show a value we don't have — the effect combo
  and the brightness slider stay disabled until the daemon's configured
  state arrives (first poll), and the % label shows an ellipsis instead
  of flashing a fake "0 %". Guarded by S40.
- Hardening: the fan-frame re-prime now pauses 0.2 s after LED packets.
  Lived incident: after a morning of LED packets followed within
  microseconds by fan frames, the pad's LED controller went deaf to
  every lighting command (fan control kept working); only a full power
  cycle plus the pad's ON button recovered it. Guarded by S41.
- Wave validated on hardware: direction "right" sweeps right-to-left
  when facing the pad.

## [0.6.0] — 2026-10-05

- LED strip control, in a dedicated **Lighting tab** of the full view
  (media-player plasmoid pattern; the tab bar never moves, the popup keeps
  its geometry). Effects: Default (untouched), Off, Static, Spectrum, Wave,
  and **Heat** — color and brightness follow the CPU temperature (green and
  dim when cool, red and fully bright in the danger zone around 93 °C).
- Static color picks through KDE's native `ColorButton` (standard color
  dialog); brightness slider for every effect except Heat; a framed
  description explains each effect as you select it.
- Protocol replicates padctl/openrazer byte-for-byte (transaction 0x1F,
  class 0x0F, XOR crc); the configured lighting is restored on daemon
  restart. Config: `led.json` (auto-created, default "keep").
- **Optimistic updates**: every commit (mode, effect, brightness, color,
  floor) applies instantly in the UI with a 4 s poll lock; a spinner in the
  tab bar marks pending application; a failed commit falls back to the
  daemon's truth on release.
- Helper: `led` verbs (color accepted with or without the leading '#'); the
  status line grows to 12 fields (LED effect, brightness, color); the daemon
  status file publishes `led`, `led_brightness`, `led_color`.
- Fix: the brightness/color controls initialize from the daemon's
  configured state instead of arbitrary defaults.
- Fix: garbage pad RPM spikes (5000+). The pad's feature report buffer
  echoes the last written frame, so LED packets polluted the RPM bytes
  (a 40% brightness byte read as 5100 RPM); reads beyond the pad's
  ceiling are now rejected and the fan frame is re-sent after every LED
  write. Guarded by S38.
- UI: the pad readout is labeled "Pad fan"; screenshot tooling pre-seeds
  the chart history (capture variants only) so captures no longer wait
  for the 4-minute rolling window.

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
