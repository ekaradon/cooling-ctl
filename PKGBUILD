# Maintainer: ekaradon <ekaradon@users.noreply.github.com>
pkgname=cooling-ctl
pkgver=0.6.0
pkgrel=1
pkgdesc="Plasma 6 plasmoid + daemon: temperatures, internal fans and Razer Laptop Cooling Pad control (silent curve / game mode, signal-based, no restarts)"
arch=(any)
url="https://github.com/ekaradon/cooling-ctl"
license=(GPL-2.0-or-later)
replaces=(fw16-coolingctl)
depends=(kirigami libplasma plasma-workspace plasma5support kdeclarative python python-hidapi)
makedepends=(git)
options=(!strip !debug)
source=("git+https://github.com/ekaradon/cooling-ctl.git#tag=v$pkgver")
sha256sums=('SKIP')

package() {
    # plasmoid
    local plasmoid_dir="$pkgdir/usr/share/plasma/plasmoids/org.coolingctl"
    install -dm755 "$plasmoid_dir"
    cp -a --no-preserve=ownership \
        "$srcdir/cooling-ctl/plasmoid/org.coolingctl/." "$plasmoid_dir/"
    # normalisation des modes : les sources locales peuvent etre en 600,
    # un plasmoid installe doit etre lisible par tous
    find "$plasmoid_dir" -type d -exec chmod 755 {} +
    find "$plasmoid_dir" -type f -exec chmod 644 {} +
    chmod 755 "$plasmoid_dir/contents/code/coolingctl.sh"

    # daemon
    install -Dm755 "$srcdir/cooling-ctl/daemon/coolingctld.py" \
        "$pkgdir/usr/lib/cooling-ctl/coolingctld.py"

    # unit utilisateur
    install -Dm644 "$srcdir/cooling-ctl/systemd/coolingctl.service" \
        "$pkgdir/usr/lib/systemd/user/coolingctl.service"

    # regle udev (acces sans root au pad)
    install -Dm644 "$srcdir/cooling-ctl/udev/99-razer-coolingpad.rules" \
        "$pkgdir/usr/lib/udev/rules.d/99-razer-coolingpad.rules"
}
