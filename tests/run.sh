#!/bin/sh
# Suite de tests fw16-coolingctl.
#   ./run.sh              -> tests unitaires + helper + intégration + QML + lint
#   SKIP_INTEGRATION=1    -> ignorer les tests contre le daemon live
#   RUN_SMOKE=1           -> + test de chargement du plasmoid (plasmawindowed,
#                            exige une copie installée du plasmoid)
#   COOLINGCTL_REFERENCE=/chemin/razer-coolingpad-fancurve.py
#                         -> + tests de parité du protocole HID (sinon sautés)
#   COOLINGCTL_PYTHON=/chemin/python
#                         -> interpréteur alternatif fournissant le module hid
#
# Résolution des outils portable (aucun chemin absolu) :
#   - outils Qt 6 : via `qmake6 -query QT_HOST_BINS` (le chemin réel de
#     l'installation Qt 6 de la machine), sinon PATH. NB : sur Arch, le
#     `qmltestrunner` du PATH est celui de Qt 5 -> QT_HOST_BINS d'abord.
#   - imports QML : via `qmake6 -query QT_INSTALL_QML`.
#   - python : le python du PATH si `hid` y est disponible, sinon
#     $COOLINGCTL_PYTHON (interpréteur arbitraire fourni explicitement).
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
    echo "aucun interpréteur python avec le module hid (COOLINGCTL_PYTHON pour en fournir un)" >&2
    exit 1
fi

echo "== outils : qmltestrunner=${QMLTR:-AUCUN} qmllint=${QMLLINT:-AUCUN} imports=${QMLDIR:-defaut} python=$PY =="

echo "== fw16-coolingctl : tests unitaires + helper =="
env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_coolingctld.py" -v || exit 1
env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_helper.py" -v || exit 1
env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_structure.py" -v || exit 1

if [ "${SKIP_INTEGRATION:-0}" != "1" ]; then
    echo "== intégration (daemon live) =="
    env -u LD_LIBRARY_PATH "$PY" -m unittest discover -s "$DIR" -p "test_integration.py" -v || exit 1
fi

if [ -n "$QMLTR" ]; then
    echo "== aperçu compact (logique QML via qmltestrunner) =="
    env -u LD_LIBRARY_PATH QT_QPA_PLATFORM=offscreen "$QMLTR" -input "$DIR/tst_compact.qml" 2>&1 \
        | grep -E "PASS|FAIL|Totals" || exit 1
else
    echo "== SKIP : qmltestrunner introuvable (tests QML ignorés) =="
fi

if [ -n "$QMLLINT" ]; then
    echo "== analyse statique (qmllint, config .qmllint.ini du projet) =="
    cd "$ROOT" || exit 1
    LINT_ARGS=""
    [ -n "$QMLDIR" ] && LINT_ARGS="-I $QMLDIR"
    for f in "$ROOT/plasmoid/org.coolingctl/contents/ui/main.qml" \
             "$ROOT/plasmoid/org.coolingctl/contents/ui/compact-logic.js" \
             "$DIR/tst_compact.qml"; do
        out=$(env -u LD_LIBRARY_PATH "$QMLLINT" $LINT_ARGS "$f" 2>&1)
        if echo "$out" | grep -qE "^Warning|^Error"; then
            echo "ECHEC lint : $(basename "$f")"
            echo "$out" | grep -E "^Warning|^Error" | head -6
            exit 1
        fi
        echo "  OK : $(basename "$f")"
    done
else
    echo "== SKIP : qmllint introuvable =="
fi

if [ "${RUN_SMOKE:-0}" = "1" ]; then
    echo "== smoke test plasmoid (plasmawindowed 8 s) =="
    # pre-requis : le smoke n'a de sens que contre une copie INSTALLEE
    # (plasmawindowed rend une fenetre vide et muette pour un applet inconnu)
    if [ ! -d /usr/share/plasma/plasmoids/org.coolingctl ] \
       && [ ! -d "${HOME}/.local/share/plasma/plasmoids/org.coolingctl" ]; then
        echo "ECHEC : le plasmoid org.coolingctl n'est pas installé" >&2
        exit 1
    fi
    LOG=$(mktemp)
    env -u LD_LIBRARY_PATH timeout 8 plasmawindowed org.coolingctl > "$LOG" 2>&1
    # critere unique du smoke (identique au Makefile) : le log doit rester VIDE
    if [ -s "$LOG" ]; then
        echo "ECHEC : erreurs QML au chargement"; cat "$LOG"; rm -f "$LOG"; exit 1
    fi
    echo "OK : chargement sans erreur QML"
    rm -f "$LOG"
fi

echo "== tout est vert =="
