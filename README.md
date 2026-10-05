# cooling-ctl

A silent-first control stack for the **Razer Laptop Cooling Pad** on Linux: a
user daemon owning the pad's HID interface exclusively (signal-based mode
switching, no restarts ever) and a KDE Plasma 6 plasmoid with live
temperatures, fan speeds, an RPM chart, a stepped fan-floor slider and
full control of the pad's RGB LED strip — including a Heat mode where the
strip itself becomes a thermal gauge.
Built around a Framework Laptop 16 (AMD), not limited to it.

| | Dark | Light |
|---|---|---|
| **Full view** | ![Full view, dark](screenshots/expanded-dark.png) | ![Full view, light](screenshots/expanded-light.png) |
| **Panel view** | ![Panel view, dark](screenshots/compact-dark.png) | ![Panel view, light](screenshots/compact-light.png) |

## Requirements

- KDE **Plasma 6**, Python 3 with `python-hidapi`
- A **Razer Laptop Cooling Pad** (USB `1532:0f43`) — the pad control target
- An AMD SoC with **k10temp**; internal-fan and dGPU readouts are written
  for the Framework 16 layout (see `AGENTS.md`)

## Installation (Arch Linux)

```sh
makepkg -si
```

| Path | Content |
|---|---|
| `/usr/share/plasma/plasmoids/org.coolingctl/` | plasmoid |
| `/usr/lib/cooling-ctl/coolingctld.py` | daemon |
| `/usr/lib/systemd/user/coolingctl.service` | user unit |
| `/usr/lib/udev/rules.d/99-razer-coolingpad.rules` | unprivileged pad access |

Other distributions: copy the same four pieces to the equivalent paths.

## Setup

```sh
systemctl --user enable --now coolingctl.service
```

Add the widget: right-click the panel → *Add widgets* → **Cooling Control**.

The daemon creates `~/.config/coolingctl/` with sensible defaults on first
start — edit them freely, `SIGHUP` reloads. Reference:

`silent-curve.json` — temperature → percent curve, linear interpolation:

```json
{
    "curve": [
        { "temp": 0,  "percent": 0 },
        { "temp": 76, "percent": 20 },
        { "temp": 85, "percent": 55 },
        { "temp": 98, "percent": 100 }
    ],
    "interval": 3,
    "hysteresis": 2,
    "sensors": "auto"
}
```

`game-floor.json` — a single-point curve; its **first point's percent is the
game mode fan floor** (the pad never runs below it while gaming):

```json
{
    "curve": [
        { "temp": 0, "percent": 33 }
    ],
    "interval": 3,
    "hysteresis": 2,
    "sensors": "auto"
}
```

Hook games through gamemode (flips the pad into game mode on launch, back on
exit or crash):

```ini
# ~/.config/gamemode.ini
[custom]
start="systemctl --user kill --signal=SIGUSR1 coolingctl.service"
end="systemctl --user kill --signal=SIGUSR2 coolingctl.service"
```

## Usage

| Signal | Mode | Behavior |
|---|---|---|
| `SIGUSR1` | game | fan floor, held in daemon memory |
| `SIGUSR2` | silent | curve against k10temp |
| `SIGWINCH` | free | releases control (pad firmware) |
| `SIGHUP` | — | reload the config files |

```sh
systemctl --user kill --signal=SIGUSR1 coolingctl.service
```

Live state is published atomically every 3 s in
`$XDG_RUNTIME_DIR/coolingctl.status`
(`mode,temp,floor_pct,floor_rpm,rpm_cmd,rpm_reported,pad_present,led,led_brightness,led_color`).
The helper `coolingctl.sh status` prints
`tctl|fan1|fan2|pad_rpm|mode|floor_pct|gpu|cpu|gpu_pct|led|led_brightness|led_color`;
actions: `set-floor <pct>`, `mode <game|silent|free>`,
`led <keep|off|static|spectrum|wave|heat>`, `led static <#rrggbb>`,
`led wave <left|right>`, `led bright <0-100>`.

### LED strip

The plasmoid drives the pad's Chroma strip from a dedicated Lighting tab:

- **Default** — no LED command is ever sent, the pad keeps its factory behavior
- **Off**, **Static** (KDE's native color picker), **Spectrum**, **Wave**
- **Heat** — the strip becomes a thermal gauge: color and brightness follow
  the CPU temperature, green and dim when cool, red and fully bright in the
  danger zone around 93 °C

Brightness applies to every effect except Heat (driven by the temperature).
Every change is applied optimistically in the UI and confirmed by the daemon.
Configuration lives in `~/.config/coolingctl/led.json` (auto-created, `SIGHUP`
to reload); the configured lighting is restored on daemon restart.

## Upgrading

pacman never restarts user services. After an upgrade the daemon and the
plasmoid keep running the old code until restarted:

```sh
systemctl --user daemon-reload && systemctl --user restart coolingctl.service
systemctl --user restart plasma-plasmashell.service   # plasmoid QML only
```

## Development

```sh
make test        # unit + structural + integration + QML + lint
make check       # + smoke + package build
```

Test options and the full architecture/conventions guide: `AGENTS.md`.
Screenshots are regenerated from the real widget by
`tools/capture-screenshots.sh`.

## License & credits

GPL-2.0-or-later (see `LICENSE`).

The animated cat — the `my-active-*-symbolic.svg` frames and the pacing
formula — comes from the **CatWalk** plasmoid by Yuri Saurov
(GPL-2.0-or-later), whose art traces back to the **RunCat** project by
Takuto Nakamura (upstream RunCatNeo is Apache-2.0). The fan HID protocol
follows the reverse-engineered `razer-coolingpad-linux` community work; the
LED protocol replicates **padctl** (hbmartin/razer-cooling-pad-mac), which
mirrors openrazer's `razerchromacommon.c`.
