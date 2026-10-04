#!/bin/sh
# capture-screenshots.sh — regenerate screenshots/ from the real widget.
#
# Pipeline (validated 2026-10-04):
#   - deploys throwaway plasmoid variants under DIFFERENT ids (.shot for the
#     full view, .cshot for the compact one) — deploying the panel's own id
#     crashes plasmashell (SIGSEGV), never do that;
#   - full view: the window stays alive CHART_WAIT seconds (default 240 = the
#     chart's 4-minute window) so the chart is fully populated; themes are
#     switched on the LIVE window (plasma-apply-lookandfeel) so dark and
#     light come from the same run without losing the chart;
#   - compact view: a 420x56 taskbar-like strip, frameGeometry first then
#     noBorder, capture, crop to the content bounding box;
#   - always restores the theme it started from.
#
# Requirements: Plasma 6 (plasmawindowed, spectacle, plasma-apply-lookandfeel,
# kbuildsycoca6, kreadconfig6), busctl, and python3+PIL (or ffmpeg) for the
# compact crop.
#
# Options (environment):
#   OUT_DIR=screenshots   output directory
#   CHART_WAIT=240        seconds to let the chart fill (full view)
#   LIGHT_THEME=org.kde.breeze.desktop
#
# The machine's theme is recorded at start and restored on exit (trap).

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/plasmoid/org.coolingctl"
LOCAL="$HOME/.local/share/plasma/plasmoids"
OUT_DIR="${OUT_DIR:-$ROOT/screenshots}"
CHART_WAIT="${CHART_WAIT:-240}"
LIGHT_THEME="${LIGHT_THEME:-org.kde.breeze.desktop}"
DARK_THEME="${DARK_THEME:-org.kde.breezedark.desktop}"
KWIN_LOG_UNIT="plasma-kwin_wayland"

mkdir -p "$OUT_DIR"

# --- theme bookkeeping -------------------------------------------------------
THEME0=$(kreadconfig6 --file kdeglobals --group KDE --key LookAndFeelPackage)
restore_theme() {
    kreadconfig6 --file kdeglobals --group KDE --key LookAndFeelPackage \
        | grep -q "^$THEME0$" || \
        plasma-apply-lookandfeel -a "$THEME0" >/dev/null 2>&1
}
cleanup() {
    restore_theme
    pkill -x plasmawindowed 2>/dev/null
    rm -rf "$LOCAL/org.coolingctl.shot" "$LOCAL/org.coolingctl.cshot"
    kbuildsycoca6 --noincremental >/dev/null 2>&1
}
trap cleanup EXIT INT TERM

# --- helpers -----------------------------------------------------------------
deploy_variant() { # <suffix> <preferred>
    local id="org.coolingctl.$1"
    rm -rf "$LOCAL/$id"
    cp -r "$SRC" "$LOCAL/$id"
    sed -i "s/\"Id\": \"org.coolingctl\"/\"Id\": \"$id\"/" "$LOCAL/$id/metadata.json"
    [ "$2" = "full" ] && \
        sed -i "s/preferredRepresentation: compactRepresentation/preferredRepresentation: fullRepresentation/" \
            "$LOCAL/$id/contents/ui/main.qml"
    chmod 755 "$LOCAL/$id/contents/code/coolingctl.sh"
}

kw_run() { # <js body>: unique path per loadScript call (duplicates never run)
    local js="/tmp/kw-capture-$$-$RANDOM.js"
    printf '%s\n' "$1" > "$js"
    local id
    id=$(busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting \
          loadScript s "$js" | awk '{print $2}')
    busctl --user call org.kde.KWin "/Scripting/Script$id" \
        org.kde.kwin.Script run >/dev/null 2>&1
    rm -f "$js"
}

focus_and_shape() { # <w> <h> — frameGeometry BEFORE noBorder (async apply);
                    # pass empty sizes to only focus (natural window size)
    local geom=""
    [ -n "${1:-}" ] && geom="w.frameGeometry = { x: 1200, y: 400, width: $1, height: $2 };"
    kw_run "
for (const w of workspace.windowList()) {
    if (w.resourceClass == \"org.kde.plasmawindowed\") {
        $geom
        w.noBorder = true;
        workspace.activeWindow = w;   // w.active is read-only
    }
}"
    sleep 2   # the geometry apply is asynchronous
}

capture_active() { # <out.png>
    kw_run "
for (const w of workspace.windowList()) {
    if (w.resourceClass == \"org.kde.plasmawindowed\") {
        workspace.activeWindow = w;
    }
}"
    sleep 1
    spectacle -b -n -a -o "$1"
}

crop_strip() { # <in.png> <out.png> <dark|light>: content bbox on a plain window
    if python3 -c "from PIL import Image" 2>/dev/null; then
        python3 - "$1" "$2" "$3" <<'EOF'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert('RGB')
w, h = im.size
px = im.load()
theme = sys.argv[3]
def content(p):
    r, g, b = p[:3]
    if max(r, g, b) - min(r, g, b) > 30:
        return True                      # colored pixel
    m = (r + g + b) // 3
    return m > 140 if theme == "dark" else m < 110
xs = [x for y in range(h) for x in range(w) if content(px[x, y])]
if xs:
    x0 = max(0, min(xs) - 12)
    im.crop((x0, 0, min(w, max(xs) + 13), h)).save(sys.argv[2])
else:
    im.save(sys.argv[2])
EOF
    elif command -v ffmpeg >/dev/null 2>&1; then
        ffmpeg -y -loglevel error -i "$1" -vf "crop=367:56" "$2"
    else
        cp "$1" "$2"   # no cropper: keep the raw 420x56 strip
    fi
}

set_theme() { plasma-apply-lookandfeel -a "$1" >/dev/null 2>&1; sleep 5; }

# theme propagation to a live window is asynchronous and the apply itself
# can silently fail (e.g. racing kbuildsycoca): verify the captured
# background (corner pixel), re-apply the theme and retry on mismatch
capture_until() { # <out.png> <dark|light> — capture, verify bg, re-apply+retry
    local out="$1" want="$2" i corner theme
    theme="$DARK_THEME"; [ "$want" = light ] && theme="$LIGHT_THEME"
    for i in 0 1 2 3; do
        [ "$i" -gt 0 ] && set_theme "$theme"
        capture_active "$out"
        corner=$(python3 -c "
from PIL import Image
im = Image.open('$out').convert('RGB')
p = im.getpixel((3, 3))
print((p[0] + p[1] + p[2]) // 3)
" 2>/dev/null || echo -1)
        if [ "$want" = dark ] && [ "$corner" -lt 100 ] 2>/dev/null; then return 0; fi
        if [ "$want" = light ] && [ "$corner" -gt 160 ] 2>/dev/null; then return 0; fi
        echo "   bg=$corner, want $want — re-applying $theme (try $i)"
    done
    echo "WARN: $out may not be $want-themed (bg=$corner)"
    return 1
}

# --- full view: one 4-minute window, theme switched on the live window -------
echo "== full view: deploying org.coolingctl.shot =="
deploy_variant shot full
kbuildsycoca6 --noincremental >/dev/null 2>&1

set_theme "$DARK_THEME"
echo "== waiting ${CHART_WAIT}s for the chart to fill =="
setsid -f plasmawindowed org.coolingctl.shot >/dev/null 2>&1 &
sleep "$CHART_WAIT"

focus_and_shape "" ""   # natural window size, as validated
echo "== capturing full view (dark) =="
capture_until "$OUT_DIR/expanded-dark.png" dark

set_theme "$LIGHT_THEME"
echo "== capturing full view (light, same window) =="
capture_until "$OUT_DIR/expanded-light.png" light
pkill -x plasmawindowed; sleep 2

# --- compact view: taskbar-like strip ----------------------------------------
echo "== compact view: deploying org.coolingctl.cshot =="
deploy_variant cshot compact
kbuildsycoca6 --noincremental >/dev/null 2>&1
setsid -f plasmawindowed org.coolingctl.cshot >/dev/null 2>&1 &
set_theme "$DARK_THEME"
sleep 6
focus_and_shape 420 56
echo "== capturing compact (dark) =="
capture_until "$OUT_DIR/compact-dark.raw.png" dark
set_theme "$LIGHT_THEME"
capture_until "$OUT_DIR/compact-light.raw.png" light
restore_theme

crop_strip "$OUT_DIR/compact-dark.raw.png" "$OUT_DIR/compact-dark.png" dark
crop_strip "$OUT_DIR/compact-light.raw.png" "$OUT_DIR/compact-light.png" light
rm -f "$OUT_DIR/compact-dark.raw.png" "$OUT_DIR/compact-light.raw.png"

echo "== done: $OUT_DIR =="
