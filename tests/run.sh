#!/bin/sh
# Suite de tests cooling-ctl.
#   ./run.sh              -> unit + helper + integration + QML + lint
#   SKIP_INTEGRATION=1    -> skip the live-daemon tests
#   RUN_SMOKE=1           -> + plasmoid load test (plasmawindowed,
#                            requires an installed copy of the plasmoid)
#   COOLINGCTL_REFERENCE=/chemin/razer-coolingpad-fancurve.py
#                         -> + HID protocol parity tests (skipped otherwise)
#   COOLINGCTL_PYTHON=/chemin/python
#                         -> alternate interpreter providing the hid module
#
# Portable tool resolution (no absolute paths):
#   - Qt 6 tools: via `qmake6 -query QT_HOST_BINS` (the real path of
'#     the machine Qt 6 installation), else PATH. Note: on Arch, the'
'#     the PATH `qmltestrunner` is the Qt 5 one -> QT_HOST_BINS first.'
#   - QML imports: via `qmake6 -query QT_INSTALL_QML`.
#   - python: the PATH python if `hid` is available there, else
#     $COOLINGCTL_PYTHON (arbitrary interpreter given explicitly).
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DIR")"

qt6_bin() {
    if command -v qmake6 >/dev/null 2>&1; then
        bins=$(env -u LD_LIBRARY_PATH qmake6 -query QT_HOST_BINS 2>/dev/null)
        [ -x "$bins/qmltestrunner" ] && { echo "$bins"; return; }
    fi
    echo ""
}

QTBIN=$(qt6_bin)
resolve_tool() { # resolve_tool <nom> : QT_HOST_BINS d'abord, PATH ensuite
    if [ -n "$QTBIN" ] && [ -x "$QTBIN/$1" ]; then echo "$QTBIN/$1"; return; fi
    command -v "$1" 2>/dev/null || echo ""
}

QMLTR=$(resolve_tool qmltestrunner)
QMLLINT=$(resolve_tool qmllint)
QMLDIR=$(env -u LD_LIBRARY_PATH qmake6 -query QT_INSTALL_QML 2>/dev/null || echo "")

if python3 -c "import hid" >/dev/null 2>&1; then
    PY=python3
elif [ -n "${COOLINGCTL_PYTHON:-}" ] && [ -x "$COOLINGCTL_PYTHON" ]; then
    PY="$COOLINGCTL_PYTHON"
else
    echo "no python interpreter with the hid module (COOLINGCTL_PYTHON to provide one)" >&2
    exit 1
fi

echo "== outils : qmltestrunner=${QMLTR:-AUCUN} qmllint=${QMLLINT:-AUCUN} imports=${QMLDIR:-defaut} python=$PY =="

echo "== cooling-ctl : tests unitaires + helper =="
env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_coolingctld.py" -v || exit 1
env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_helper.py" -v || exit 1
env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_structure.py" -v || exit 1

if [ "${SKIP_INTEGRATION:-0}" != "1" ]; then
    echo "== integration (live daemon) =="
    env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_integration.py" -v || exit 1
fi

if [ -n "$QMLTR" ]; then
    echo "== compact view (QML logic via qmltestrunner) =="
    QML_OUT=$(env -u LD_LIBRARY_PATH QT_QPA_PLATFORM=offscreen "$QMLTR" -input "$DIR/tst_compact.qml" 2>&1)
    echo "$QML_OUT" | grep -E "PASS|FAIL|Totals"
    # the display grep always matches: gate on actual failures
    if echo "$QML_OUT" | grep -qE "^FAIL"; then
        echo "ECHEC : tests QML en echec" >&2
        exit 1
    fi
else
    echo "== SKIP: qmltestrunner not found (QML tests skipped) =="
fi

if [ -n "$QMLLINT" ]; then
    echo "== static analysis (qmllint, project .qmllint.ini) =="
    cd "$ROOT" || exit 1
    LINT_ARGS=""
    [ -n "$QMLDIR" ] && LINT_ARGS="-I $QMLDIR"
    for f in "$ROOT/plasmoid/org.coolingctl/contents/ui/main.qml" \
             "$ROOT/plasmoid/org.coolingctl/contents/ui/compact-logic.js" \
             "$DIR/tst_compact.qml"; do
        out=$(env -u LD_LIBRARY_PATH "$QMLLINT" $LINT_ARGS "$f" 2>&1)
        if echo "$out" | grep -qE "^Warning|^Error"; then
            echo "LINT FAIL: $(basename "$f")"
            echo "$out" | grep -E "^Warning|^Error" | head -6
            exit 1
        fi
        echo "  OK : $(basename "$f")"
    done
else
    echo "== SKIP: qmllint not found =="
fi

if [ "${RUN_SMOKE:-0}" = "1" ]; then
    echo "== plasmoid smoke test (plasmawindowed 8 s) =="
    # prerequisite: the smoke only makes sense against an INSTALLED copy
    # (plasmawindowed renders a silent empty window for an unknown applet)
    if [ ! -d /usr/share/plasma/plasmoids/org.coolingctl ] \
       && [ ! -d "${HOME}/.local/share/plasma/plasmoids/org.coolingctl" ]; then
        echo "FAIL: plasmoid org.coolingctl is not installed" >&2
        exit 1
    fi
    LOG=$(mktemp)
    env -u LD_LIBRARY_PATH timeout 8 plasmawindowed org.coolingctl > "$LOG" 2>&1
    # single smoke criterion (same as the Makefile): the log must stay EMPTY
    if [ -s "$LOG" ]; then
        echo "FAIL: QML load errors"; cat "$LOG"; rm -f "$LOG"; exit 1
    fi
    echo "OK: load without QML errors"
    rm -f "$LOG"
fi

echo "== all green =="
