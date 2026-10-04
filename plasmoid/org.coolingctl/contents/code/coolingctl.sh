#!/bin/sh
# fw16-coolingctl helper - source unique de donnees/actions du plasmoid.
# Toutes les donnees pad viennent du daemon coolingctl (fichier d'etat),
# le reste est lu dans /sys. Les actions sont des signaux, jamais des restarts.
#
# Commandes :
#   status               -> ligne a 9 champs
#                           "tctl|fan1|fan2|pad_rpm|mode|plateau_pct|gpu|cpu|gpu_pct"
#   set-plateau <pct>    -> ecrit le plateau + SIGHUP (application a chaud)
#   mode <jeu|silencieux|libre> -> SIGUSR1/SIGUSR2/SIGWINCH
#
# Surcharges d'environnement (tests / autres machines) :
#   COOLINGCTL_STATUS_FILE, COOLINGCTL_CPU_STATE, COOLINGCTL_CURVES_DIR,
#   COOLINGCTL_GAMING_JSON, COOLINGCTL_DRM_DIR

STATUS_FILE="${COOLINGCTL_STATUS_FILE:-${XDG_RUNTIME_DIR:-/run/user/1000}/coolingctl.status}"
CPU_STATE="${COOLINGCTL_CPU_STATE:-${XDG_RUNTIME_DIR:-/run/user/1000}/coolingctl.cpu}"
DRM_DIR="${COOLINGCTL_DRM_DIR:-/sys/class/drm}"
CONFIG_DIR="${COOLINGCTL_CURVES_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/coolingctl}"
GAMING_JSON="${COOLINGCTL_GAMING_JSON:-$CONFIG_DIR/gaming-plateau.json}"

hwmon_by_name() {
    dirname "$(grep -lx "$1" /sys/class/hwmon/hwmon*/name 2>/dev/null | head -1)"
}

readf() { cat "$1" 2>/dev/null; }

stget() { sed -n "s/^$1=//p" "$STATUS_FILE" 2>/dev/null; }

# charge CPU en % : delta /proc/stat depuis l'invocation precedente
# (le helper est appele toutes les 2 s par le plasmoid)
cpu_pct() {
    read -r _ u n s i iow irq soft steal _ < /proc/stat || { echo 0; return; }
    total=$((u + n + s + i + iow + irq + soft + steal))
    idle=$((i + iow))
    CPU=0
    if [ -r "$CPU_STATE" ]; then
        read -r pt pi < "$CPU_STATE" 2>/dev/null
        dt=$((total - pt)); di=$((idle - pi))
        if [ "$dt" -gt 0 ] 2>/dev/null; then
            CPU=$((100 * (dt - di) / dt))
        fi
    fi
    [ "$CPU" -lt 0 ] && CPU=0
    [ "$CPU" -gt 100 ] && CPU=100
    echo "$total $idle" > "$CPU_STATE"
    echo "$CPU"
}

cmd_status() {
    K10=$(hwmon_by_name k10temp)
    EC=$(hwmon_by_name cros_ec)
    TCTL=$(readf "$K10/temp1_input")
    [ -n "$TCTL" ] && TCTL=$((TCTL / 1000))
    F1=$(readf "$EC/fan1_input")
    F2=$(readf "$EC/fan2_input")

    # GPU : dGPU (edge) si lisible (reveille = rendu en cours), sinon iGPU
    GPU=""
    for lbl in /sys/class/hwmon/hwmon*/temp*_label; do
        [ "$(readf "$lbl")" = "edge" ] || continue
        dev=$(basename "$(readlink -f "$(dirname "$lbl")/device")")
        case "$dev" in
            *c4*) IGPU=$(readf "${lbl%_label}_input") ;;
            *)    DGPU=$(readf "${lbl%_label}_input") ;;
        esac
    done
    [ -n "$DGPU" ] && GPU=$((DGPU / 1000))
    [ -z "$GPU" ] && [ -n "$IGPU" ] && GPU=$((IGPU / 1000))
    [ -z "$GPU" ] && GPU=-1

    # activite GPU : meme GPU que la temperature affichee (dGPU sinon iGPU),
    # via gpu_busy_percent d'amdgpu (vide quand le dGPU dort)
    GPUPCT=-1
    DGPU_CARD=""; IGPU_CARD=""
    for card in "$DRM_DIR"/card*/device; do
        addr=$(basename "$(readlink -f "$card")")
        case "$addr" in
            *03*) DGPU_CARD="$card" ;;
            *c4*) IGPU_CARD="$card" ;;
        esac
    done
    SRC=""
    if [ -n "$DGPU" ] && [ -r "$DGPU_CARD/gpu_busy_percent" ]; then
        SRC="$DGPU_CARD/gpu_busy_percent"
    elif [ -r "$IGPU_CARD/gpu_busy_percent" ]; then
        SRC="$IGPU_CARD/gpu_busy_percent"
    fi
    if [ -n "$SRC" ]; then
        v=$(readf "$SRC")
        case "$v" in ''|*[!0-9]*) v=-1 ;; esac
        [ "$v" -gt 100 ] 2>/dev/null && v=100
        GPUPCT=$v
    fi

    # etat pad depuis le daemon (courbe -> "silencieux", libre -> "libre")
    MODE=$(stget mode)
    [ "$MODE" = "jeu" ] || [ "$MODE" = "libre" ] || MODE=silencieux
    PAD_RPM=$(stget rpm_reported)
    PLATEAU=$(stget plateau_pct)
    [ -z "$PAD_RPM" ] && PAD_RPM=-1
    [ -z "$PLATEAU" ] && PLATEAU=-1

    CPU=$(cpu_pct)

    echo "${TCTL:--1}|${F1:--1}|${F2:--1}|${PAD_RPM}|${MODE}|${PLATEAU}|${GPU}|${CPU}|${GPUPCT}"
}

cmd_set_plateau() {
    PCT="$1"
    case "$PCT" in
        ''|*[!0-9]*) echo "pct invalide"; exit 1 ;;
    esac
    [ "$PCT" -lt 0 ] && PCT=0
    [ "$PCT" -gt 100 ] && PCT=100
    sed -i "s/\"percent\": *[0-9]*/\"percent\": $PCT/g" "$GAMING_JSON" || exit 1
    env -u LD_LIBRARY_PATH systemctl --user kill --signal=SIGHUP coolingctl.service
    echo "ok"
}

cmd_mode() {
    case "$1" in
        jeu)        SIG=SIGUSR1 ;;
        silencieux) SIG=SIGUSR2 ;;
        libre)      SIG=SIGWINCH ;;
        *) echo "mode invalide"; exit 1 ;;
    esac
    env -u LD_LIBRARY_PATH systemctl --user kill --signal=$SIG coolingctl.service
}

case "$1" in
    status)       cmd_status ;;
    set-plateau)  cmd_set_plateau "$2" ;;
    mode)         cmd_mode "$2" ;;
    *)            echo "usage: $0 status|set-plateau <pct>|mode <jeu|silencieux|libre>"; exit 1 ;;
esac
