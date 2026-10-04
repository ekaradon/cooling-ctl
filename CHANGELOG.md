# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
