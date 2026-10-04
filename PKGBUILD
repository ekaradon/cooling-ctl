# Maintainer: ekaradon <ekaradon@users.noreply.github.com>
pkgname=fw16-coolingctl
pkgver=0.3.0
pkgrel=1
pkgdesc="Plasmoid Plasma 6 + daemon : temperatures, ventilateurs internes et controle du Razer Laptop Cooling Pad (courbe silencieuse / mode jeu, signaux sans restart)"
arch=(any)
url="https://github.com/ekaradon/cooling-ctl"
license=(GPL-2.0-or-later)
depends=(kirigami libplasma plasma-workspace plasma5support python python-hidapi)
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
        "$pkgdir/usr/lib/fw16-coolingctl/coolingctld.py"

    # unit utilisateur
    install -Dm644 "$srcdir/cooling-ctl/systemd/coolingctl.service" \
        "$pkgdir/usr/lib/systemd/user/coolingctl.service"

    # regle udev (acces sans root au pad)
    install -Dm644 "$srcdir/cooling-ctl/udev/99-razer-coolingpad.rules" \
        "$pkgdir/usr/lib/udev/rules.d/99-razer-coolingpad.rules"
}
