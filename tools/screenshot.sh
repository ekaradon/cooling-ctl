#!/usr/bin/env bash
# screenshot.sh — regenerate the four README screenshots from the live widget.
#
# One command, zero manual steps. Runs the documented pipeline end to end:
#   deploy .shot / .cshot variants -> smoke gate -> launch -> fill -> focus
#   (KWin scripting) -> capture dark & light (theme switch on the live
#   window) -> crop the compact strips -> sanity gates -> cleanup.
#
# Usage:  tools/screenshot.sh [--out DIR] [--fill SECONDS]
#   --out    output directory (default: screenshots/). Use /tmp for a test
#            run that must not touch the committed files.
#   --fill   chart fill time for the full view (default: 240).
#
# Requirements: the coolingctl daemon running (live data), the pad present,
# Plasma 6 with qdbus6 / spectacle / kbuildsycoca6 / plasma-apply-lookandfeel,
# python3 with Pillow for the compact crop.
#
# Plasma 6 API realities this script encodes (all hit the hard way):
#   - plasma-apply-lookandfeel -a THEME applies; -l LISTS. A wrong flag
#     fails silently (exit 0, theme unchanged).
#   - KWin scripting: loadScript(path, pluginName) only REGISTERS a script
#     and returns an int id; scripts actually run when Scripting.start()
#     is called, and there is no /Scripting/<id> object to poke afterwards.
#     print() lands in the kwin_wayland journal with a flush lag — never
#     use prints for control flow, only fixed sleeps.
#   - spectacle -b -n -a captures the ACTIVE window: always (re)focus
#     right before, and set noBorder = true or the decoration pollutes
#     the capture.
#   - Detached launch must redirect stdout/stderr to /dev/null or the
#     calling shell's pipe stays open until the window dies.

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT="$REPO/screenshots"
FILL=240

while [ $# -gt 0 ]; do
    case "$1" in
        --out)  OUT=$2; shift 2 ;;
        --fill) FILL=$2; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

ID_SHOT="org.coolingctl.shot"
ID_CSHOT="org.coolingctl.cshot"
THEME_DARK="org.kde.breezedark.desktop"
THEME_LIGHT="org.kde.breeze.desktop"
PLASMOIDS="$HOME/.local/share/plasma/plasmoids"
QMLCACHE="$HOME/.cache/plasmawindowed/qmlcache"

# The sandbox/IDE pollutes LD_LIBRARY_PATH and breaks system Qt tools.
run() { env -u LD_LIBRARY_PATH "$@"; }

log() { echo "== $*"; }
die() { echo "FAIL: $*" >&2; exit 1; }

# ---------------------------------------------------------------- preflight
for tool in qdbus6 spectacle kbuildsycoca6 plasmawindowed plasma-apply-lookandfeel python3 systemctl kreadconfig6; do
    command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"
done
python3 -c 'import PIL' 2>/dev/null || die "python3 Pillow is required for the compact crop"
[ "$(systemctl --user is-active coolingctl.service 2>/dev/null || true)" = "active" ] \
    || die "coolingctl.service is not active — screenshots need the live daemon"
mkdir -p "$OUT"

ORIG_THEME=$(run kreadconfig6 --file kdeglobals --group KDE --key LookAndFeelPackage)
THEME_CHANGED=0

# ------------------------------------------------------------------- helpers
deploy_variant() { # $1 = id, $2 = full|compact
    local dst="$PLASMOIDS/$1" rep=compactRepresentation
    [ "$2" = full ] && rep=fullRepresentation
    rm -rf "$dst"
    cp -r "$REPO/plasmoid/org.coolingctl" "$dst"
    sed -i "s|\"Id\": \"org.coolingctl\"|\"Id\": \"$1\"|" "$dst/metadata.json"
    sed -i "s|preferredRepresentation: compactRepresentation|preferredRepresentation: $rep|" "$dst/contents/ui/main.qml"
    chmod 755 "$dst/contents/code/coolingctl.sh"
}

remove_variants() {
    rm -rf "$PLASMOIDS/$ID_SHOT" "$PLASMOIDS/$ID_CSHOT"
}

smoke_variant() { # $1 = id — the plasmawindowed log must stay EMPTY
    local log
    log=$(mktemp)
    log "smoke gate: $1"
    run timeout 8 plasmawindowed "$1" >"$log" 2>&1 || true
    if [ -s "$log" ]; then
        cat "$log"
        rm -f "$log"
        die "smoke gate failed for $1 — the log must stay empty"
    fi
    rm -f "$log"
}

KWIN_JS_NAMES=""
JS_N=0
kwin_run() { # $1 = js file path — registers, runs via start(), unloads
    JS_N=$((JS_N + 1))
    local name="coolingctl-shots-$$-$JS_N"
    run qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$1" "$name" >/dev/null
    run qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start >/dev/null
    KWIN_JS_NAMES="$KWIN_JS_NAMES $name"
}

# Focus the plasmawindowed window; optionally resize it. $1 = js file,
# $2 = width (0 = keep), $3 = height. noBorder always: the decoration
# must not leak into the capture.
kwin_gen_js() {
    cat > "$1" <<EOF
var wl = workspace.windowList(); var t = null;
for (var i = 0; i < wl.length; i++) {
    if (String(wl[i].resourceClass).indexOf("plasmawindowed") !== -1) { t = wl[i]; }
}
if (t) {
    t.noBorder = true;
    if ($2 > 0) { t.frameGeometry = { x: 200, y: 200, width: $2, height: $3 }; }
    workspace.activeWindow = t;
}
EOF
}

focus_window() { kwin_gen_js "$TMP/js-focus-$((JS_N + 1)).js" 0 0; kwin_run "$TMP/js-focus-$((JS_N + 1)).js"; sleep 2; }
resize_window() { # $1 w, $2 h — frameGeometry apply is asynchronous; unique
                  # js path per call: KWin silently skips duplicate paths
    kwin_gen_js "$TMP/js-geom-$((JS_N + 1)).js" "$1" "$2"
    kwin_run "$TMP/js-geom-$((JS_N + 1)).js"
    sleep 2
}

apply_theme() { # $1 = LaF package — ALWAYS -a; -l only lists themes
    run plasma-apply-lookandfeel -a "$1" >/dev/null 2>&1
    THEME_CHANGED=1
    sleep 5
}

kill_windows() {
    pkill -f 'plasmawindowed org[.]coolingctl[.]shot'  2>/dev/null || true
    pkill -f 'plasmawindowed org[.]coolingctl[.]cshot' 2>/dev/null || true
    sleep 1
}

capture() { # $1 = output png — captures the ACTIVE window
    run spectacle -b -n -a -o "$1"
    sleep 2
}

TMP=$(mktemp -d)
cleanup() {
    kill_windows
    if [ "$THEME_CHANGED" = 1 ] && [ -n "$ORIG_THEME" ]; then
        run plasma-apply-lookandfeel -a "$ORIG_THEME" >/dev/null 2>&1 || true
    fi
    for name in $KWIN_JS_NAMES; do
        run qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$name" >/dev/null 2>&1 || true
    done
    remove_variants
    rm -rf "$QMLCACHE"
    run kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
    rm -rf "$TMP"
}
trap cleanup EXIT

# ------------------------------------------------------------- sanity gates
check_pair() { # $1 = -dark file, $2 = -light file — theme must actually differ
    python3 - "$1" "$2" <<'EOF' || die "sanity gate failed — a 'light' capture is not light (theme switch silently failed?)"
import sys
from PIL import Image, ImageStat
for f, lo, hi, what in ((sys.argv[1], 0, 100, "dark"), (sys.argv[2], 150, 256, "light")):
    st = ImageStat.Stat(Image.open(f).convert("L"))
    lum = st.mean[0]
    ok = lo <= lum <= hi and st.stddev[0] > 5
    print(f"{f}: mean={lum:.1f} stddev={st.stddev[0]:.1f} ({what})")
    if not ok:
        sys.exit(1)
EOF
}

crop_compact() { # $1 = raw 420x56 capture, $2 = output file
    python3 - "$1" "$2" <<'EOF' || die "compact crop failed (empty content?)"
import sys
from PIL import Image, ImageChops
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
bg = im.getpixel((w - 5, h // 2))
diff = ImageChops.difference(im, Image.new("RGB", im.size, bg))
bbox = diff.convert("L").point(lambda p: 255 if p > 12 else 0).getbbox()
if not bbox or bbox[2] - bbox[0] < 100:
    sys.exit(1)
# Repo convention: full height, content plus an 11 px right margin.
im.crop((0, 0, min(w, bbox[2] + 11), h)).save(sys.argv[2])
print(f"{sys.argv[2]}: {min(w, bbox[2] + 11)}x{h} (content bbox {bbox})")
EOF
}

# ------------------------------------------------------------------ pipeline
log "deploying variants $ID_SHOT (full) and $ID_CSHOT (compact)"
remove_variants
deploy_variant "$ID_SHOT" full
deploy_variant "$ID_CSHOT" compact
rm -rf "$QMLCACHE"
run kbuildsycoca6 --noincremental >/dev/null 2>&1
smoke_variant "$ID_SHOT"
smoke_variant "$ID_CSHOT"

log "full view: launching, filling the chart for ${FILL}s"
( run setsid -f plasmawindowed "$ID_SHOT" >/dev/null 2>&1 </dev/null )
sleep "$FILL"

log "full view: dark capture"
focus_window
capture "$TMP/expanded-dark.png"

log "full view: switching to light on the live window"
apply_theme "$THEME_LIGHT"
focus_window
capture "$TMP/expanded-light.png"

log "full view done — closing, launching the compact strip"
kill_windows
( run setsid -f plasmawindowed "$ID_CSHOT" >/dev/null 2>&1 </dev/null )
sleep 15

log "compact: resize to 420x56, capture (still light)"
resize_window 420 56
capture "$TMP/compact-light.png"

log "compact: back to dark"
apply_theme "$THEME_DARK"
focus_window
capture "$TMP/compact-dark.png"

log "closing windows, cropping compact strips"
kill_windows

crop_compact "$TMP/compact-dark.png"  "$OUT/compact-dark.png"
crop_compact "$TMP/compact-light.png" "$OUT/compact-light.png"
cp "$TMP/expanded-dark.png"  "$OUT/expanded-dark.png"
cp "$TMP/expanded-light.png" "$OUT/expanded-light.png"

check_pair "$OUT/expanded-dark.png"  "$OUT/expanded-light.png"
check_pair "$OUT/compact-dark.png"   "$OUT/compact-light.png"

log "OK — wrote $(ls -1 "$OUT"/expanded-dark.png "$OUT"/expanded-light.png "$OUT"/compact-dark.png "$OUT"/compact-light.png | xargs -n1 basename | tr '\n' ' ')"
