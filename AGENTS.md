# AGENTS.md — working guide for the cooling-control repository

Conventions and operating rules for any agent (or human) contributing to this
repository. Read this before touching anything; read `README.md` for the
user-facing picture.

## What this project is

One Arch package, `fw16-coolingctl`, shipping two cooperating pieces:

```
plasmoid/org.coolingctl/          Plasma 6 widget (UI, reads, actions)
daemon/coolingctld.py             user daemon, EXCLUSIVE owner of the pad HID
systemd/coolingctl.service        user unit running the daemon
udev/99-razer-coolingpad.rules    unprivileged access to the pad (1532:0f43)
tests/                            whole quality suite, entry point run.sh
PKGBUILD                          packaging (makepkg)
```

Data flow — one direction, no shortcuts:

```
pad (HID) ── coolingctld ──> $XDG_RUNTIME_DIR/coolingctl.status (atomic)
                                   │
/sys (k10temp, cros_ec, amdgpu) ── coolingctl.sh (helper, exec'd by the UI)
                                   │
                                   └── plasmoid (2 s poll) ──> UI
```

Rules that follow from this shape:

- **Only the daemon touches the pad.** Everything else reads the status file.
  Never parse daemon journals, never open the HID from the UI or tests while
  the daemon runs.
- **Actions are signals, never restarts**: SIGUSR1 game, SIGUSR2 curve,
  SIGWINCH free, SIGHUP config reload. Killing/restarting the daemon to
  change modes is a regression.
- **UI never blocks**: sensors are polled through the helper subprocess; a
  failed/absent pad or sensor degrades to an em-dash or an empty string per
  value (the chart shows « collecte des données… » before the first poll),
  never to an error popup.
- Helper `status` contract: 9 pipe-separated fields
  `tctl|fan1|fan2|pad_rpm|mode|plateau_pct|gpu|cpu|gpu_pct`. The plasmoid
  parses 9 with a fallback to 7. Changing the field count touches: helper,
  plasmoid parser, `tests/test_helper.py`, README — all four, always.

## Coding conventions

- Comments in French in the sources (existing style); new files may be
  English or French but stay consistent within a file.
- The plasmoid is QML/JS; pure logic lives in `contents/ui/compact-logic.js`
  as `.pragma library` functions **so it is unit-testable via qmltestrunner**
  (QML UI files are not loadable in tests). New compact-view logic goes
  there, not inline in `main.qml`.
- Python: stdlib only (plus `hid`). The daemon must run on the plain system
  interpreter, no venv.
- Configs: JSON under `~/.config/coolingctl/` (XDG). The daemon never writes
  them; the helper's `set-plateau` rewrites `gaming-plateau.json` then SIGHUPs.
- License: GPL-2.0-or-later. Imported third-party art/code must be compatible
  and credited in README + the file header (see the cat frames:
  CatWalk → RunCat lineage).

## Testing — the non-negotiable part

`tests/run.sh` is the gate: unit (daemon/helper), structural
(`test_structure.py` — each S-number encodes a bug actually hit), integration
against the live daemon, QML logic via qmltestrunner, qmllint. Options:
`SKIP_INTEGRATION`, `RUN_SMOKE`, `COOLINGCTL_PYTHON`, `COOLINGCTL_REFERENCE`.

House rules:

1. **A test that cannot fail is not a test.** Before landing any new test,
   mutate the code it targets (break the line) and watch the suite go red,
   then restore. This is enforced by review, not by tooling — do it anyway.
2. **No fix without its test.** Every bug fix lands together with the
   structural or unit test that would have caught it.
3. **Plasmoid load errors are silent in `run.sh`.** qmllint has a known blind
   spot: "no matching signal found for handler" is muted by
   `UnqualifiedAccess=disable` in `.qmllint.ini` (needed for i18n/delegate
   false positives). A handler on a non-existent signal kills the whole
   widget (falls back to a generic settings icon). `test_structure.py`
   covers the known cases structurally; the smoke gate — `RUN_SMOKE=1` in
   `run.sh` and `make smoke`, same success criterion: the plasmawindowed
   log must stay EMPTY — is the real proof and is mandatory before any
   deploy. It only has meaning against an INSTALLED copy: the gate fails if
   `org.coolingctl` is not in `/usr/share/plasma/plasmoids` or
   `~/.local/share/plasma/plasmoids` (plasmawindowed silently renders an
   empty window for an unknown applet, which would defeat the check).

## Plasmoid iteration ritual (development installs)

Plasma caches a plugin's QML for the whole session. Adding/removing the
widget reloads NOTHING. The cycle:

1. Edit sources → `tests/run.sh` green.
2. Copy `plasmoid/org.coolingctl` to
   `~/.local/share/plasma/plasmoids/org.coolingctl/` (chmod 755 the helper)
   → `kbuildsycoca6 --noincremental`.
3. Smoke: `timeout 8 plasmawindowed org.coolingctl` → log must be EMPTY.
   (plasmawindowed shows the compact view.)
4. `systemctl --user restart plasma-plasmashell.service`.
5. After user validation: bump `pkgver`/`pkgrel` in `PKGBUILD` and
   `Version` in `metadata.json`, `make check` (includes packaging build),
   install, then **delete the `~/.local` copy** — the package must be the
   only installed source.

## Packaging

- `make pkg` (or `makepkg -f`) builds `fw16-coolingctl-<ver>-<rel>-any.pkg.tar.zst`.
- Modes are normalized at install (dirs 755, files 644, helper 755) — a
  source tree with wrong modes must never leak into the package.
- Before publishing: fill the `# Maintainer:` line and the real `url` in
  `PKGBUILD`, tag the release, update `CHANGELOG.md`.

## Repository hygiene

- No personal data: no usernames, emails, personal absolute paths, hostnames.
  Test-support paths come from environment variables, never hardcoded.
- No build artifacts committed (`pkg/`, `*.pkg.tar.*` are gitignored).
- Commit messages: imperative subject line + body explaining why. Amend
  freely while the repository has not been published.
