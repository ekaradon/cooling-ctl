# AGENTS.md — working guide for the cooling-control repository

Conventions and operating rules for any agent (or human) contributing to this
repository. Read this before touching anything; read `README.md` for the
user-facing picture.

## What this project is

One Arch package, `cooling-ctl`, shipping two cooperating pieces:

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
- Helper `status` contract: 12 pipe-separated fields
  `tctl|fan1|fan2|pad_rpm|mode|floor_pct|gpu|cpu|gpu_pct|led|led_brightness|led_color`.
  The plasmoid parses with per-field fallbacks. Changing the field count touches: helper,
  plasmoid parser, `tests/test_helper.py`, README — all four, always.

## Coding conventions

- All comments, docstrings, UI strings and tool output are in English — the
  protocol too: the status file publishes `mode=silent|game|free`, the helper
  CLI verbs are `game|silent|free`, passthrough from the daemon. Changing this
  vocabulary is a breaking change: bump the version and update daemon, helper,
  plasmoid and tests together.
- The plasmoid is QML/JS; pure logic lives in `contents/ui/compact-logic.js`
  as `.pragma library` functions **so it is unit-testable via qmltestrunner**
  (QML UI files are not loadable in tests). New compact-view logic goes
  there, not inline in `main.qml`.
- Symbolic SVGs (the cat) are NOT recolored by KSvg outside an applet
  context: render them as `Kirigami.Icon { isMask: true; color:
  Kirigami.Theme.textColor }` so they adapt to dark and light themes
  (S31 in `tests/test_structure.py` guards this).
- Python: stdlib only (plus `hid`). The daemon must run on the plain system
  interpreter, no venv.
- Configs: JSON under `~/.config/coolingctl/` (XDG). The daemon never writes
  them; the helper's `set-floor` rewrites `game-floor.json` then SIGHUPs.
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
3. **Plasmoid load errors are silent in `run.sh`.** qmllint's "no matching
   signal found for handler" is categorized `[unqualified]`:
   `UnqualifiedAccess=warning` in `.qmllint.ini` (re-enabled 0.6.2 — it
   catches handlers on non-existent signals, which kill the whole widget
   into a generic settings-icon fallback). The known Plasma false
   positives (the `i18n()` global, `root` inside the representations) are
   suppressed line-by-line in `main.qml` — never disable the rule again.
   `test_structure.py` covers the known cases structurally; the smoke
   gate — `RUN_SMOKE=1` in `run.sh` and `make smoke`, same success
   criterion: the plasmawindowed
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
   **Crash trap (two plasmashell SIGSEGVs, 2026-10-04): never deploy a
   `.local` copy under the SAME id as a widget that is live in the panel and
   run kbuildsycoca — plasmashell segfaults as the plasmoid is swapped under
   it. For screenshots/tests, deploy a variant under a DIFFERENT id
   (`org.coolingctl.shot`, `.cshot`, …), never the panel id.**
3. Smoke: `timeout 8 plasmawindowed org.coolingctl` → log must be EMPTY.
   (plasmawindowed shows the compact view.)
   **Stale-QML trap (cost an hour of phantom debugging, 2026-10-04):
   plasmawindowed serves compiled QML from
   `~/.cache/plasmawindowed/qmlcache/` — editing main.qml and relaunching is
   NOT enough, the window can keep showing the old UI. Purge that directory
   whenever an iteration's changes seem invisible.**
4. `systemctl --user restart plasma-plasmashell.service`.
5. After user validation: bump `pkgver`/`pkgrel` in `PKGBUILD` and
   `Version` in `metadata.json`, `make check` (includes packaging build),
   install, **restart `coolingctl.service`** (pacman never restarts user
   services — the old daemon keeps running from the deleted binary),
   then **delete the `~/.local` copy** — the package must be the
   only installed source.

## Screenshots (`screenshots/`)

Generated from the real widget, never mocked:

- **Full view**: variant `.shot` (different id,
  `preferredRepresentation: fullRepresentation`), launched with
  `setsid -f plasmawindowed <id>` (survives the calling shell). Keep the
  window alive **4 minutes** so the chart fills, then
  `spectacle -b -n -a` after focusing it via KWin scripting
  (`workspace.activeWindow = w` — `w.active` is read-only). Switch themes
  with `plasma-apply-lookandfeel` on the LIVE window: it recolors without
  losing the chart, so dark and light come from the same 4-minute run.
- **Panel (compact) view**: variant `.cshot`, resized via
  `w.frameGeometry = {x, y, width, height}` (plain JS object; the apply is
  **asynchronous** — do not trust a print right after) into a taskbar-like
  420x56 strip, `noBorder = true`, capture, crop the content bounding box.
- KWin scripting API notes: `loadScript` needs a UNIQUE path per call
  (duplicates silently do not run), `resize()` does not exist on
  XdgToplevelWindow, resourceClass is `org.kde.plasmawindowed`, `print()`
  lands in the plasma-kwin_wayland journal.
- Always restore the machine's theme after a light/dark pass.

## Packaging

- `make pkg` (or `makepkg -f`) builds `cooling-ctl-<ver>-<rel>-any.pkg.tar.zst`.
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
