#!/usr/bin/env python3
"""coolingctld - single daemon controlling the Razer Laptop Cooling Pad.

Single owner of the HID device, internal modes, signal-based switching
without ever restarting the process:

  SIGUSR1 -> game mode  (fixed floor held in daemon memory)
  SIGUSR2 -> silent mode (silent-curve.json curve)
  SIGWINCH-> free mode  (releases control: off report, pad firmware)
  SIGHUP  -> reload config files (floor changed, mode unchanged)
             NB: the floor used by game mode is the in-memory one;
             any change to the json therefore goes through SIGHUP

Data:
  curve   : $XDG_CONFIG_HOME/coolingctl/silent-curve.json
  floor : $XDG_CONFIG_HOME/coolingctl/game-floor.json (first point)

State published (atomically, every loop):
  $XDG_RUNTIME_DIR/coolingctl.status : lignes cle=valeur
  mode, temp, floor_pct, floor_rpm, rpm_cmd, rpm_reported, pad_present,
  led, led_brightness, led_color

Clean stop (SIGTERM): sends the "off" report to the pad (back to firmware
behavior), like the historical controller.
"""

import json
import os
import signal
import sys
import time

try:
    import hid
except ImportError:
    print("Erreur: module hid indisponible (pip install hidapi)", file=sys.stderr)
    sys.exit(1)

VID = 0x1532
PID = 0x0F43
REPORT_LEN = 91
REPORT_ID = 0x00
MIN_RPM = 500
MAX_RPM = 3200
INTERVAL = 3

HEADER = bytearray([
    0x00, 0x02, 0x00, 0x00, 0x00, 0x03, 0x0D, 0x10, 0x01, 0x02,
    0x36, 0x00,
] + [0x00] * 78)

# Configuration: XDG Base Directory (curves = daemon config).
# Can be overridden via COOLINGCTL_CURVES_DIR.
XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
CURVES_DIR = os.environ.get("COOLINGCTL_CURVES_DIR",
                            os.path.join(XDG_CONFIG, "coolingctl"))
CURVE_FILE = os.path.join(CURVES_DIR, "silent-curve.json")
GAMING_FILE = os.path.join(CURVES_DIR, "game-floor.json")
LED_FILE = os.path.join(CURVES_DIR, "led.json")
STATUS_FILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"), "coolingctl.status")

# Sensible defaults: written on first start when the config files are
# missing (pacman never touches $HOME, so the daemon self-provisions).
DEFAULT_SILENT_CURVE = {
    "curve": [
        {"temp": 0, "percent": 0},
        {"temp": 76, "percent": 20},
        {"temp": 82, "percent": 35},
        {"temp": 85, "percent": 55},
        {"temp": 88, "percent": 75},
        {"temp": 92, "percent": 90},
        {"temp": 98, "percent": 100},
    ],
    "interval": 3,
    "hysteresis": 2,
    "sensors": "auto",
}
DEFAULT_FLOOR = {
    "curve": [{"temp": 0, "percent": 33}],   # first point = the floor
    "interval": 3,
    "hysteresis": 2,
    "sensors": "auto",
}
# "keep" never sends LED packets: least surprise on first start.
DEFAULT_LED = {
    "effect": "keep",
    "color": "#ff6600",
    "brightness": 100,
    "wave_dir": "right",
    "wave_speed": 40,
}


def ensure_configs(curves_dir=None):
    """Create the config directory and default files when missing."""
    d = curves_dir or CURVES_DIR
    os.makedirs(d, exist_ok=True)
    for name, data in (("silent-curve.json", DEFAULT_SILENT_CURVE),
                       ("game-floor.json", DEFAULT_FLOOR),
                       ("led.json", DEFAULT_LED)):
        path = os.path.join(d, name)
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
                f.write("\n")
            print(f"default config created: {path}", flush=True)


# ---------- HID protocol (identical to razer-coolingpad-fancurve) ----------
IDX_REPORT_CODE = 8
IDX_SUB_VER = 9
IDX_CURVE_ID = 10
IDX_RPM_L = 11
IDX_RPM_H = 12
IDX_CHK_L = 89
IDX_CHK_H = 90


def build_set_rpm_report(rpm):
    rpm = max(MIN_RPM, min(MAX_RPM, rpm))
    buf = bytearray(REPORT_LEN)
    buf[0] = REPORT_ID
    buf[1:91] = HEADER
    buf[IDX_REPORT_CODE] = 0x01
    buf[IDX_SUB_VER] = 0x01
    buf[IDX_CURVE_ID] = 0x05
    raw = int(round(rpm / 50.0))
    buf[IDX_RPM_L] = raw & 0xFF
    buf[IDX_RPM_H] = (raw >> 8) & 0xFF
    buf[IDX_CHK_L] = buf[IDX_RPM_L] ^ 0x0B
    buf[IDX_CHK_H] = 0x00
    return bytes(buf)


def build_off_report():
    buf = bytearray(REPORT_LEN)
    buf[0] = REPORT_ID
    buf[1:91] = HEADER
    buf[IDX_REPORT_CODE] = 0x10
    buf[IDX_SUB_VER] = 0x00
    buf[IDX_CURVE_ID] = 0x06
    buf[IDX_RPM_L] = 0x00
    buf[IDX_RPM_H] = 0x00
    buf[IDX_CHK_L] = 0x18
    buf[IDX_CHK_H] = 0x00
    return bytes(buf)


# ------------------------------ LED protocol --------------------------------
# Razer Chroma extended-matrix effects for the pad's 1x18 LED strip.
# Byte layout replicated from padctl (hbmartin/razer-cooling-pad-mac), which
# mirrors openrazer's razerchromacommon.c: transaction id 0x1F, class 0x0F,
# VARSTORE storage on the zeroth (whole-strip) LED, XOR crc at buf[89].
# CRC covers buf[3..88] (the transaction id is excluded).

LED_TID = 0x1F
LED_CLASS = 0x0F
LED_CMD_EFFECT = 0x02
LED_CMD_BRIGHTNESS = 0x04
LED_VARSTORE = 0x01
LED_ZERO_LED = 0x00
LED_WAVE_SPEED = 0x28          # padctl's default wave speed


def build_led_report(cmd, size, args):
    buf = bytearray(REPORT_LEN)
    buf[0] = REPORT_ID
    buf[2] = LED_TID
    buf[6] = size
    buf[7] = LED_CLASS
    buf[8] = cmd
    for i, b in enumerate(args):
        buf[9 + i] = b
    crc = 0
    for b in buf[3:89]:
        crc ^= b
    buf[89] = crc
    return bytes(buf)


def led_off_report():
    return build_led_report(LED_CMD_EFFECT, 0x06, [LED_VARSTORE, LED_ZERO_LED, 0x00])


def led_static_report(r, g, b):
    return build_led_report(LED_CMD_EFFECT, 0x09,
                            [LED_VARSTORE, LED_ZERO_LED, 0x01,
                             0x00, 0x00, 0x01, r, g, b])


def led_spectrum_report():
    return build_led_report(LED_CMD_EFFECT, 0x06,
                            [LED_VARSTORE, LED_ZERO_LED, 0x03])


def led_wave_report(direction="right", speed=LED_WAVE_SPEED):
    dir_byte = 0x01 if direction == "left" else 0x02
    return build_led_report(LED_CMD_EFFECT, 0x06,
                            [LED_VARSTORE, LED_ZERO_LED, 0x04, dir_byte, speed])


def led_brightness_report(brightness):
    return build_led_report(LED_CMD_BRIGHTNESS, 0x03,
                            [LED_VARSTORE, LED_ZERO_LED, brightness])


def heat_color(temp, t_min=45.0, t_max=95.0):
    """Classic thermal ramp: green (cool) -> yellow -> orange -> red (hot).
    Pure function, unit-tested; drives the 'heat' LED effect."""
    import colorsys
    t = max(t_min, min(t_max, temp))
    f = (t - t_min) / (t_max - t_min)
    hue = (1.0 - f) * 120.0            # 120 deg = green, 0 deg = red
    r, g, b = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def heat_brightness(temp, t_min=45.0, t_max=93.0):
    """Heat effect brightness ramp: 5 % when cool, 100 % in the danger
    zone (93 deg = the chart's threshold band). Linear, pure, tested."""
    t = max(t_min, min(t_max, temp))
    f = (t - t_min) / (t_max - t_min)
    return int(round(5 + 95 * f))


def parse_led_color(s):
    """'#rrggbb' -> (r, g, b); None when invalid."""
    try:
        s = str(s).lstrip("#")
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        pass
    return None


def apply_led(dev, cfg):
    """Send the configured LED effect. One-shot effects only — the 'heat'
    effect is applied continuously by the main loop. Returns True when at
    least one packet was sent (the caller must re-prime the RPM frame)."""
    if dev is None or not cfg:
        return False
    effect = cfg.get("effect", "keep")
    if effect == "keep":
        return False
    sent = False
    b = cfg.get("brightness")
    if isinstance(b, (int, float)) and 0 <= b <= 100:
        send(dev, led_brightness_report(int(b * 255 / 100)))
        sent = True
    if effect == "off":
        send(dev, led_off_report())
        sent = True
    elif effect == "spectrum":
        send(dev, led_spectrum_report())
        sent = True
    elif effect == "wave":
        send(dev, led_wave_report(cfg.get("wave_dir", "right"),
                                  int(cfg.get("wave_speed", LED_WAVE_SPEED))))
        sent = True
    elif effect == "static":
        rgb = parse_led_color(cfg.get("color", "#ff6600"))
        if rgb:
            send(dev, led_static_report(*rgb))
            sent = True
    return sent


def prime_rpm_frame(dev, st):
    """The pad's feature report buffer ECHOES the last written frame: after
    an LED packet, read_rpm decodes LED bytes as garbage RPM (lived bug:
    a 40% brightness byte read as 5100 RPM). Re-send the last fan/off frame
    so the next read returns real telemetry."""
    if dev is None:
        return
    frame = getattr(st, "last_frame", None)
    if frame is not None:
        send(dev, frame)


def open_device():
    try:
        dev = hid.device()
        dev.open(VID, PID)
        return dev
    except Exception:
        return None


def send(dev, report):
    try:
        dev.send_feature_report(report)
        return True
    except Exception:
        return False


def read_rpm(dev):
    try:
        data = dev.get_feature_report(REPORT_ID, REPORT_LEN)
        rpm = (data[IDX_RPM_L] | (data[IDX_RPM_H] << 8)) * 50
        # the feature report buffer ECHOES the last written frame: after an
        # LED packet the bytes decode to garbage (a 40% brightness byte at
        # IDX_RPM_L read as 5100 RPM — lived bug). The pad tops at MAX_RPM;
        # anything beyond that is buffer pollution, not telemetry.
        return rpm if rpm <= MAX_RPM * 1.25 else None
    except Exception:
        return None


# ------------------------------ sensors -----------------------------------

def find_k10temp():
    import glob
    for name_path in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            with open(name_path) as f:
                if f.read().strip() == "k10temp":
                    d = os.path.dirname(name_path)
                    p = os.path.join(d, "temp1_input")
                    if os.access(p, os.R_OK):
                        return p
        except OSError:
            continue
    return None


def read_temp(sensor_path):
    try:
        with open(sensor_path) as f:
            return float(f.read().strip()) / 1000.0
    except OSError:
        return None


# -------------------------------- state -----------------------------------

class State:
    def __init__(self):
        self.mode = "silent"        # silent | game | free
        self.curve = []              # [(temp, percent)]
        self.floor_pct = 30
        self.last_rpm = None
        self.read_fails = 0
        self.led = {}                # led.json contents (effect, color, ...)
        self.last_heat_rgb = None    # dedup for the heat effect
        self.last_heat_bright = None
        self.reload()

    def reload(self):
        self.curve = self.load_curve(CURVE_FILE)
        pct = self.load_floor(GAMING_FILE)
        if pct is not None:
            self.floor_pct = pct
        self.led = self.load_led(LED_FILE)
        self.last_heat_rgb = None    # force a re-apply
        self.last_heat_bright = None

    @staticmethod
    def load_led(path):
        try:
            with open(path) as f:
                cfg = json.load(f)
                if isinstance(cfg, dict) and "effect" in cfg:
                    return cfg
        except Exception as e:
            print(f"unreadable LED config ({e})", file=sys.stderr)
        return {}

    @staticmethod
    def load_curve(path):
        try:
            with open(path) as f:
                pts = [(p["temp"], p["percent"])
                       for p in json.load(f)["curve"]]
            return sorted(pts)
        except Exception as e:
            print(f"unreadable curve ({e}), floor seul disponible", file=sys.stderr)
            return []

    @staticmethod
    def load_floor(path):
        try:
            with open(path) as f:
                pts = json.load(f)["curve"]
                return float(pts[0]["percent"])
        except Exception as e:
            print(f"unreadable floor ({e})", file=sys.stderr)
            return None


def interpolate(curve, temp):
    if not curve:
        return None
    if temp <= curve[0][0]:
        return curve[0][1]
    if temp >= curve[-1][0]:
        return curve[-1][1]
    for (t0, p0), (t1, p1) in zip(curve, curve[1:]):
        if t0 <= temp <= t1:
            if t1 == t0:
                return p1
            return p0 + (p1 - p0) * (temp - t0) / (t1 - t0)


def pct_to_rpm(pct):
    pct = max(0.0, min(100.0, pct))
    rpm = MIN_RPM + pct / 100.0 * (MAX_RPM - MIN_RPM)
    return int(round(rpm / 50.0)) * 50


def write_status(mode, temp, floor_pct, rpm_cmd, rpm_rep, pad_present,
                 led="keep", led_brightness=100, led_color="#ff6600"):
    tmp = STATUS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(f"mode={mode}\n")
            f.write(f"temp={temp if temp is not None else -1}\n")
            f.write(f"floor_pct={floor_pct}\n")
            f.write(f"floor_rpm={pct_to_rpm(floor_pct)}\n")
            f.write(f"rpm_cmd={rpm_cmd if rpm_cmd is not None else -1}\n")
            f.write(f"rpm_reported={rpm_rep if rpm_rep is not None else -1}\n")
            f.write(f"pad_present={1 if pad_present else 0}\n")
            f.write(f"led={led}\n")
            f.write(f"led_brightness={led_brightness}\n")
            f.write(f"led_color={led_color}\n")
        os.replace(tmp, STATUS_FILE)
    except OSError as e:
        print(f"cannot write status file: {e}", file=sys.stderr)


# --------------------------------- main -----------------------------------
def main():

    ensure_configs()
    st = State()
    pending = {"mode": None, "reload": False}


    def handle(sig, frame):
        if sig == signal.SIGUSR1:
            pending["mode"] = "game"
        elif sig == signal.SIGUSR2:
            pending["mode"] = "silent"
        elif sig == signal.SIGWINCH:
            pending["mode"] = "free"
        elif sig == signal.SIGHUP:
            pending["reload"] = True


    signal.signal(signal.SIGUSR1, handle)
    signal.signal(signal.SIGUSR2, handle)
    signal.signal(signal.SIGWINCH, handle)
    signal.signal(signal.SIGHUP, handle)

    running = [True]


    def handle_term(sig, frame):
        running[0] = False


    signal.signal(signal.SIGINT, handle_term)
    signal.signal(signal.SIGTERM, handle_term)

    k10 = find_k10temp()
    dev = open_device()
    if dev is None:
        print("pad absent at startup, waiting...", flush=True)

    # restore the configured lighting on boot/restart (padctl parity):
    # the strip keeps its firmware state across daemon restarts
    if apply_led(dev, st.led):
        prime_rpm_frame(dev, st)

    last_rep = None
    print("coolingctld up (silent mode)", flush=True)
    while running[0]:
        # signals
        if pending["mode"] is not None:
            new_mode = pending["mode"]
            pending["mode"] = None
            if new_mode != st.mode:
                if new_mode == "free" and dev is not None:
                    off_frame = build_off_report()
                    send(dev, off_frame)
                    st.last_frame = off_frame
                    print("control released (off report)", flush=True)
                st.mode = new_mode
                st.last_rpm = None  # force a rewrite on mode change
                print(f"mode -> {st.mode}", flush=True)
        if pending["reload"]:
            pending["reload"] = False
            st.reload()
            st.last_rpm = None
            print(f"config reloaded (floor {st.floor_pct}%)", flush=True)
            if apply_led(dev, st.led):
                prime_rpm_frame(dev, st)

        # CPU sensor (re-resolve if it disappears)
        temp = read_temp(k10) if k10 else None
        if temp is None:
            k10 = find_k10temp()
            temp = read_temp(k10) if k10 else None

        # target depending on mode (free = no control)
        pct = None
        if temp is not None and st.mode != "free":
            if st.mode == "game":
                pct = st.floor_pct
            else:
                pct = interpolate(st.curve, temp)
        rpm = pct_to_rpm(pct) if pct is not None else None

        # dedup (device granularity)
        if rpm is not None and st.last_rpm is not None and abs(rpm - st.last_rpm) < 50:
            rpm = st.last_rpm

        # reconnect if needed
        if dev is None:
            dev = open_device()
            if dev is not None:
                st.last_rpm = None
                print("pad connected", flush=True)

        # apply
        pad_present = dev is not None
        if dev is not None and rpm is not None and rpm != st.last_rpm:
            frame = build_set_rpm_report(rpm)
            if not send(dev, frame):
                dev.close()
                dev = None
                pad_present = False
                print("write failed, reconnecting...", flush=True)
            else:
                st.last_rpm = rpm
                st.last_frame = frame   # for prime_rpm_frame after LED writes

        # heat LED effect: color AND brightness follow the temperature,
        # each deduped so we only send what changed
        if st.led.get("effect") == "heat" and temp is not None and dev is not None:
            rgb = heat_color(temp)
            if rgb != st.last_heat_rgb:
                send(dev, led_static_report(*rgb))
                st.last_heat_rgb = rgb
                prime_rpm_frame(dev, st)
            bright = heat_brightness(temp)
            if bright != st.last_heat_bright:
                send(dev, led_brightness_report(int(bright * 255 / 100)))
                st.last_heat_bright = bright
                prime_rpm_frame(dev, st)

        # read back
        if dev is not None:
            rep = read_rpm(dev)
            if rep is None:
                st.read_fails += 1
                if st.read_fails >= 5:
                    try:
                        dev.close()
                    except Exception:
                        pass
                    dev = None
                    st.read_fails = 0
                    print("RPM read failed x5, reopening device", flush=True)
            else:
                st.read_fails = 0
                last_rep = rep
        write_status(st.mode, temp, st.floor_pct, st.last_rpm, last_rep, pad_present,
                    st.led.get("effect", "keep"), int(st.led.get("brightness", 100)),
                    st.led.get("color", "#ff6600"))

        time.sleep(INTERVAL)

    if dev is not None:
        send(dev, build_off_report())
        try:
            dev.close()
        except Exception:
            pass
    print("coolingctld stopped (pad released)", flush=True)


if __name__ == "__main__":
    main()
