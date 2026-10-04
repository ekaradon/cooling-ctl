# cooling-control — quality & packaging pipeline
#
#   make test      unit + structural + integration + QML + lint (the gate)
#   make lint      qmllint alone (fast feedback while editing QML)
#   make smoke     plasmoid load smoke test (requires the plasmoid installed)
#   make pkg       build the Arch package via makepkg
#   make check     test + lint + smoke + pkg  (pre-release gate)
#   make clean     remove build artifacts
#
# Environment pass-through: SKIP_INTEGRATION, RUN_SMOKE, COOLINGCTL_PYTHON,
# COOLINGCTL_REFERENCE (see tests/run.sh).

.PHONY: test lint smoke pkg check clean

PKG   := $(shell grep -m1 '^pkgname=' PKGBUILD | cut -d= -f2)
VER   := $(shell grep -m1 '^pkgver=' PKGBUILD | cut -d= -f2)
REL   := $(shell grep -m1 '^pkgrel=' PKGBUILD | cut -d= -f2)
QB    := $(shell env -u LD_LIBRARY_PATH qmake6 -query QT_HOST_BINS 2>/dev/null)
QMD   := $(shell env -u LD_LIBRARY_PATH qmake6 -query QT_INSTALL_QML 2>/dev/null)
QMLLINT := $(shell if [ -n "$(QB)" ] && [ -x "$(QB)/qmllint" ]; then echo "$(QB)/qmllint"; else command -v qmllint 2>/dev/null; fi)

test:
	cd tests && ./run.sh

lint:
	@if [ -z "$(QMLLINT)" ]; then \
	    echo "SKIP : qmllint introuvable"; exit 0; \
	fi
	@rc=0; \
	for f in plasmoid/org.coolingctl/contents/ui/main.qml \
	         plasmoid/org.coolingctl/contents/ui/compact-logic.js \
	         tests/tst_compact.qml; do \
	    out=$$(env -u LD_LIBRARY_PATH "$(QMLLINT)" -I "$(QMD)" "$$f" 2>&1); \
	    if echo "$$out" | grep -qE "^Warning|^Error"; then \
	        echo "LINT FAIL : $$f"; \
	        echo "$$out" | grep -E "^Warning|^Error" | head -6; \
	        rc=1; \
	    else \
	        echo "  lint OK : $$f"; \
	    fi; \
	done; \
	exit $$rc

smoke:
	@if [ ! -d /usr/share/plasma/plasmoids/org.coolingctl ] \
	   && [ ! -d ~/.local/share/plasma/plasmoids/org.coolingctl ]; then \
	    echo "SMOKE FAIL : le plasmoid org.coolingctl n'est pas installé" \
	         "(le smoke n'a de sens que contre une copie installée)"; \
	    exit 1; \
	fi
	@LOG=$$(mktemp); \
	echo "== smoke : plasmawindowed 8 s =="; \
	env -u LD_LIBRARY_PATH timeout 8 plasmawindowed org.coolingctl > "$$LOG" 2>&1; \
	if [ -s "$$LOG" ]; then \
	    echo "SMOKE FAIL : le log doit rester vide"; cat "$$LOG"; rm -f "$$LOG"; exit 1; \
	fi; \
	echo "OK : chargement sans erreur QML"; \
	rm -f "$$LOG"

pkg:
	@env -u LD_LIBRARY_PATH makepkg -f
	@echo "package: $(PKG)-$(VER)-$(REL)-any.pkg.tar.zst"

check: test lint smoke pkg
	@echo "== check complet : tests + lint + smoke + package =="

clean:
	rm -rf pkg src *.pkg.tar.*
