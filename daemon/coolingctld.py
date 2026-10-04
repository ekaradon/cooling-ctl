#!/usr/bin/env python3
"""coolingctld - daemon unique de controle du Razer Laptop Cooling Pad.

Un seul proprietaire du device HID, modes internes, bascule par signaux
sans jamais relancer le process :

  SIGUSR1 -> mode jeu   (plateau fixe tenu en memoire par le daemon)
  SIGUSR2 -> mode courbe (courbe silent-curve.json)
  SIGWINCH-> mode libre (relache le controle : rapport off, pad firmware)
  SIGHUP  -> recharger les fichiers de config (plateau modifie, mode inchange)
             NB : le plateau utilise par le mode jeu est celui en memoire ;
             toute modification du json passe donc par un SIGHUP

Donnees :
  courbe  : $XDG_CONFIG_HOME/coolingctl/silent-curve.json
  plateau : $XDG_CONFIG_HOME/coolingctl/gaming-plateau.json (premier point)

Etat publie (atomiquement, a chaque boucle) :
  $XDG_RUNTIME_DIR/coolingctl.status : lignes cle=valeur
  mode, temp, plateau_pct, plateau_rpm, rpm_cmd, rpm_reported, pad_present

Arret propre (SIGTERM) : envoi le rapport "off" au pad (retour au comportement
firmware), comme le controleur historique.
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

# Configuration : XDG Base Directory (courbes = config du daemon).
# Surcharge possible via COOLINGCTL_CURVES_DIR.
XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
CURVES_DIR = os.environ.get("COOLINGCTL_CURVES_DIR",
                            os.path.join(XDG_CONFIG, "coolingctl"))
CURVE_FILE = os.path.join(CURVES_DIR, "silent-curve.json")
GAMING_FILE = os.path.join(CURVES_DIR, "gaming-plateau.json")
STATUS_FILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"), "coolingctl.status")


# ---------- protocole HID (identique a razer-coolingpad-fancurve) ----------
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
        return (data[IDX_RPM_L] | (data[IDX_RPM_H] << 8)) * 50
    except Exception:
        return None


# ------------------------------ capteurs ----------------------------------

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


# -------------------------------- etat -------------------------------------

class State:
    def __init__(self):
        self.mode = "courbe"          # courbe | jeu
        self.curve = []              # [(temp, percent)]
        self.plateau_pct = 30
        self.last_rpm = None
        self.read_fails = 0
        self.reload()

    def reload(self):
        self.curve = self.load_curve(CURVE_FILE)
        pct = self.load_plateau(GAMING_FILE)
        if pct is not None:
            self.plateau_pct = pct

    @staticmethod
    def load_curve(path):
        try:
            with open(path) as f:
                pts = [(p["temp"], p["percent"])
                       for p in json.load(f)["curve"]]
            return sorted(pts)
        except Exception as e:
            print(f"courbe illisible ({e}), plateau seul disponible", file=sys.stderr)
            return []

    @staticmethod
    def load_plateau(path):
        try:
            with open(path) as f:
                pts = json.load(f)["curve"]
                return float(pts[0]["percent"])
        except Exception as e:
            print(f"plateau illisible ({e})", file=sys.stderr)
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


def write_status(mode, temp, plateau_pct, rpm_cmd, rpm_rep, pad_present):
    tmp = STATUS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(f"mode={mode}\n")
            f.write(f"temp={temp if temp is not None else -1}\n")
            f.write(f"plateau_pct={plateau_pct}\n")
            f.write(f"plateau_rpm={pct_to_rpm(plateau_pct)}\n")
            f.write(f"rpm_cmd={rpm_cmd if rpm_cmd is not None else -1}\n")
            f.write(f"rpm_reported={rpm_rep if rpm_rep is not None else -1}\n")
            f.write(f"pad_present={1 if pad_present else 0}\n")
        os.replace(tmp, STATUS_FILE)
    except OSError as e:
        print(f"ecriture status impossible: {e}", file=sys.stderr)


# --------------------------------- main ------------------------------------
def main():

    st = State()
    pending = {"mode": None, "reload": False}


    def handle(sig, frame):
        if sig == signal.SIGUSR1:
            pending["mode"] = "jeu"
        elif sig == signal.SIGUSR2:
            pending["mode"] = "courbe"
        elif sig == signal.SIGWINCH:
            pending["mode"] = "libre"
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
        print("pad absent au demarrage, en attente...", flush=True)

    last_rep = None
    print("coolingctld actif (mode courbe)", flush=True)
    while running[0]:
        # signaux
        if pending["mode"] is not None:
            new_mode = pending["mode"]
            pending["mode"] = None
            if new_mode != st.mode:
                if new_mode == "libre" and dev is not None:
                    send(dev, build_off_report())
                    print("controle relache (rapport off)", flush=True)
                st.mode = new_mode
                st.last_rpm = None  # forcer la reecriture au changement de mode
                print(f"mode -> {st.mode}", flush=True)
        if pending["reload"]:
            pending["reload"] = False
            st.reload()
            st.last_rpm = None
            print(f"config rechargee (plateau {st.plateau_pct}%)", flush=True)

        # capteur CPU (re-resoudre s'il disparait)
        temp = read_temp(k10) if k10 else None
        if temp is None:
            k10 = find_k10temp()
            temp = read_temp(k10) if k10 else None

        # cible selon le mode (libre = aucun controle)
        pct = None
        if temp is not None and st.mode != "libre":
            if st.mode == "jeu":
                pct = st.plateau_pct
            else:
                pct = interpolate(st.curve, temp)
        rpm = pct_to_rpm(pct) if pct is not None else None

        # dedup (granularite du device)
        if rpm is not None and st.last_rpm is not None and abs(rpm - st.last_rpm) < 50:
            rpm = st.last_rpm

        # reconnexion si besoin
        if dev is None:
            dev = open_device()
            if dev is not None:
                st.last_rpm = None
                print("pad connecte", flush=True)

        # application
        pad_present = dev is not None
        if dev is not None and rpm is not None and rpm != st.last_rpm:
            if not send(dev, build_set_rpm_report(rpm)):
                dev.close()
                dev = None
                pad_present = False
                print("envoi HS, reconnexion...", flush=True)
            else:
                st.last_rpm = rpm

        # lecture retour
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
                    print("lecture RPM HS x5, reouverture", flush=True)
            else:
                st.read_fails = 0
                last_rep = rep
        write_status(st.mode, temp, st.plateau_pct, st.last_rpm, last_rep, pad_present)

        time.sleep(INTERVAL)

    if dev is not None:
        send(dev, build_off_report())
        try:
            dev.close()
        except Exception:
            pass
    print("coolingctld arrete (pad libere)", flush=True)


if __name__ == "__main__":
    main()
