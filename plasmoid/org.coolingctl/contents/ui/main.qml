import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.ksvg as KSvg
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as P5Support
import "compact-logic.js" as CLogic

PlasmoidItem {
    id: root

    // etat courant
    property real tctl: -1
    property real gpu: -1
    property real fan: -1
    property real padRpm: -1
    property string mode: "?"
    property real plateau: -1
    property real cpu: 0
    property real gpuLoad: -1
    property int polls: 0
    property bool sliderBusy: false   // vrai pendant le drag + 4 s apres (verrou anti snap-back)

    // pad visible tant qu'aucune mesure recue (evite le flash au demarrage),
    // puis uniquement si le pad repond
    readonly property bool padVisible: root.polls === 0 || root.padRpm >= 0

    // historique : { tctl, gpu, fan, pad }
    property var history: []
    readonly property int maxPoints: 120
    readonly property real tempMax: 100
    readonly property real tempMin: 40
    readonly property real rpmMax: 6000

    readonly property string helper: Qt.resolvedUrl("../code/coolingctl.sh").toString().replace("file://", "")

    // identite de serie (stable sur les deux themes Breeze)
    readonly property color colCpu: "#e05a45"
    readonly property color colGpu: "#9a6ee0"
    readonly property color colFan: "#3fb96a"
    readonly property color colPad: "#4f8fe0"

    function tempHealthColor(t) {
        if (t < 0) return Kirigami.Theme.disabledTextColor
        if (t < 85) return Kirigami.Theme.positiveTextColor
        if (t < 93) return Kirigami.Theme.neutralTextColor
        return Kirigami.Theme.negativeTextColor
    }

    // moyenne d'une serie sur la fenetre visible du graphique (jusqu'a 4 min)
    function avgOf(key) {
        const h = root.history
        let sum = 0, n = 0
        for (const p of h) {
            if (p[key] >= 0) { sum += p[key]; n++ }
        }
        return n > 0 ? sum / n : -1
    }

    function parseStatus(out) {
        const p = (out || "").trim().split("|")
        if (p.length < 7 || p[0] === "") return
        root.polls++
        root.tctl = parseFloat(p[0])
        const f1 = parseFloat(p[1]), f2 = parseFloat(p[2])
        root.fan = (f1 + f2) / 2
        root.padRpm = parseFloat(p[3])
        root.mode = p[4]
        root.plateau = parseFloat(p[5])
        root.gpu = parseFloat(p[6])
        root.cpu = p.length > 7 ? parseFloat(p[7]) : 0
        root.gpuLoad = p.length > 8 ? parseFloat(p[8]) : -1

        root.history = root.history.concat([{ tctl: root.tctl, gpu: root.gpu, fan: root.fan, pad: root.padRpm }])
        if (root.history.length > root.maxPoints)
            root.history = root.history.slice(-root.maxPoints)
    }

    P5Support.DataSource {
        id: poller
        engine: "executable"
        interval: 2000
        connectedSources: [root.helper + " status"]
        onNewData: (source, data) => root.parseStatus(data["stdout"])
    }

    P5Support.DataSource {
        id: runner
        engine: "executable"
        onNewData: (source, data) => runner.disconnectSource(source)
    }

    function exec(cmd) { runner.connectSource(cmd) }

    preferredRepresentation: compactRepresentation

    fullRepresentation: Item {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 28
        Layout.preferredHeight: Kirigami.Units.gridUnit * 34
        Layout.minimumWidth: Kirigami.Units.gridUnit * 24
        Layout.minimumHeight: Kirigami.Units.gridUnit * 28

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.gridUnit * 1.5
            spacing: Kirigami.Units.largeSpacing

            // -- entete : titre + badge mode --------------------------------
            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: Kirigami.Units.smallSpacing

                PlasmaComponents.Label {
                    text: i18n("COOLING")
                    font.pointSize: Application.font.pointSize * 0.9
                    font.letterSpacing: 2
                    font.weight: Font.DemiBold
                    color: Kirigami.Theme.disabledTextColor
                    Layout.fillWidth: true
                }

                Rectangle {
                    visible: root.padVisible
                    radius: height / 2
                    implicitHeight: modeLabel.implicitHeight + 2 * Kirigami.Units.smallSpacing
                    implicitWidth: modeLabel.implicitWidth + 3 * Kirigami.Units.smallSpacing
                    readonly property bool jeu: root.mode === "jeu"
                    color: jeu
                           ? Qt.rgba(Kirigami.Theme.highlightColor.r,
                                     Kirigami.Theme.highlightColor.g,
                                     Kirigami.Theme.highlightColor.b, 0.25)
                           : Kirigami.Theme.alternateBackgroundColor

                    PlasmaComponents.Label {
                        id: modeLabel
                        anchors.centerIn: parent
                        text: root.mode === "jeu" ? i18n("MODE JEU")
                         : root.mode === "libre" ? i18n("LIBRE")
                         : i18n("COURBE SILENCIEUSE")
                        color: parent.jeu ? Kirigami.Theme.highlightColor : Kirigami.Theme.disabledTextColor
                        font.pointSize: Application.font.pointSize * 0.75
                        font.letterSpacing: 1
                        font.weight: Font.DemiBold
                    }
                }
            }

            // -- zone stats : heros CPU + GPU, secondaires RPM ----------------
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing * 3

                ColumnLayout {
                    spacing: 0
                    Layout.alignment: Qt.AlignVCenter

                    PlasmaComponents.Label {
                        text: root.tctl >= 0 ? root.tctl.toFixed(0) + "°" : "—"
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2.8
                        font.weight: Font.Black
                        color: root.colCpu
                    }
                    PlasmaComponents.Label {
                        text: root.avgOf("tctl") >= 0 ? i18n("%1° moy.", Math.round(root.avgOf("tctl"))) : ""
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.75)
                        font.weight: Font.Bold
                        color: root.colCpu
                    }
                    PlasmaComponents.Label {
                        text: i18n("CPU · TCTL")
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                        font.letterSpacing: 1
                        color: Kirigami.Theme.disabledTextColor
                    }
                }

                ColumnLayout {
                    spacing: 0
                    Layout.alignment: Qt.AlignVCenter
                    PlasmaComponents.Label {
                        text: root.gpu >= 0 ? root.gpu.toFixed(0) + "°" : "—"
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2.8
                        font.weight: Font.Black
                        color: root.colGpu
                    }
                    PlasmaComponents.Label {
                        text: root.avgOf("gpu") >= 0 ? i18n("%1° moy.", Math.round(root.avgOf("gpu"))) : ""
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.75)
                        font.weight: Font.Bold
                        color: root.colGpu
                    }
                    PlasmaComponents.Label {
                        text: i18n("GPU")
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                        font.letterSpacing: 1
                        color: Kirigami.Theme.disabledTextColor
                    }
                }

                Item { Layout.fillWidth: true }

                GridLayout {
                    columns: 2
                    columnSpacing: Kirigami.Units.largeSpacing
                    rowSpacing: Kirigami.Units.smallSpacing
                    Layout.alignment: Qt.AlignVCenter

                    PlasmaComponents.Label { text: i18n("Ventilos"); font.pixelSize: Math.round(Application.font.pixelSize * 0.85); color: Kirigami.Theme.disabledTextColor }
                    PlasmaComponents.Label {
                        Layout.alignment: Qt.AlignRight
                        text: root.fan >= 0 ? Math.round(root.fan) : "—"
                        font.weight: Font.Bold
                        color: root.colFan
                    }
                    PlasmaComponents.Label { text: i18n("Pad"); visible: root.padVisible; font.pixelSize: Math.round(Application.font.pixelSize * 0.85); color: Kirigami.Theme.disabledTextColor }
                    PlasmaComponents.Label {
                        visible: root.padVisible
                        Layout.alignment: Qt.AlignRight
                        text: root.padRpm >= 0 ? Math.round(root.padRpm) : "—"
                        font.weight: Font.Bold
                        color: root.colPad
                    }
                }
            }

            // -- graphique ----------------------------------------------------
            Canvas {
                id: chart
                antialiasing: true
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: Kirigami.Units.gridUnit * 10

                Connections {
                    target: root
                    function onHistoryChanged() { chart.requestPaint() }
                }

                onPaint: {
                    const ctx = getContext("2d")
                    const W = width, H = height
                    ctx.clearRect(0, 0, W, H)

                    const mL = 28, mR = 52, mT = 16, mB = 20
                    const cw = W - mL - mR, ch = H - mT - mB
                    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
                    const yTemp = v => mT + ch * (1 - (clamp(v, root.tempMin, root.tempMax) - root.tempMin) / (root.tempMax - root.tempMin))
                    const yRpm = v => mT + ch * (1 - clamp(v, 0, root.rpmMax) / root.rpmMax)

                    // grille discrete : lignes de reference uniquement
                    ctx.globalAlpha = 0.35
                    ctx.strokeStyle = Kirigami.Theme.disabledTextColor
                    ctx.lineWidth = 1
                    ctx.font = '9px ' + Application.font.family
                    ctx.fillStyle = Kirigami.Theme.disabledTextColor

                    for (const t of [40, 60, 80, 100]) {
                        const y = yTemp(t)
                        ctx.beginPath(); ctx.moveTo(mL, y); ctx.lineTo(mL + cw, y); ctx.stroke()
                        ctx.fillText(t + "°", 2, y + 3)
                    }
                    for (const r of [0, 3000, 6000]) {
                        const y = yRpm(r)
                        ctx.fillText(r === 0 ? "0" : (r / 1000) + "k", W - mR + 6, y + 3)
                    }
                    // titres d'axes
                    ctx.font = 'bold 8px ' + Application.font.family
                    ctx.fillText("°C", 2, 9)
                    ctx.textAlign = "right"
                    ctx.fillText("RPM", W - 4, 9)
                    ctx.textAlign = "left"
                    ctx.font = '9px ' + Application.font.family
                    // bande de seuil : zone > 93 degres teintee
                    const y93 = yTemp(93)
                    ctx.fillStyle = Qt.rgba(root.colCpu.r, root.colCpu.g, root.colCpu.b, 0.10)
                    ctx.fillRect(mL, yTemp(root.tempMax), cw, y93 - yTemp(root.tempMax))
                    ctx.strokeStyle = root.colCpu
                    ctx.globalAlpha = 0.45
                    ctx.beginPath(); ctx.moveTo(mL, y93); ctx.lineTo(mL + cw, y93); ctx.stroke()
                    ctx.globalAlpha = 1

                    const h = root.history
                    if (h.length < 2) {
                        ctx.globalAlpha = 0.6
                        ctx.fillStyle = Kirigami.Theme.disabledTextColor
                        ctx.font = 'italic ' + Application.font.pixelSize + 'px ' + Application.font.family
                        ctx.textAlign = "center"
                        ctx.fillText(i18n("collecte des données…"), mL + cw / 2, mT + ch / 2)
                        ctx.textAlign = "left"
                        ctx.globalAlpha = 1
                        return
                    }

                    const xAt = i => mL + cw * (i + (root.maxPoints - h.length)) / (root.maxPoints - 1)

                    const endLabels = []

                    function drawSeries(key, color, yFn, labelFn) {
                        ctx.strokeStyle = color
                        ctx.lineWidth = 2
                        ctx.lineJoin = "round"
                        ctx.lineCap = "round"
                        ctx.beginPath()
                        let started = false, lastX = 0, lastY = 0, lastV = -1
                        for (let i = 0; i < h.length; i++) {
                            const v = h[i][key]
                            if (v < 0) { started = false; continue }
                            const x = xAt(i), y = yFn(v)
                            if (!started) { ctx.moveTo(x, y); started = true }
                            else ctx.lineTo(x, y)
                            lastX = x; lastY = y; lastV = v
                        }
                        ctx.stroke()
                        if (lastV < 0) return
                        // point + valeur courante en bout de ligne (label resolu plus tard, anti-collision)
                        ctx.fillStyle = color
                        ctx.beginPath()
                        ctx.arc(lastX, lastY, 2.5, 0, 2 * Math.PI)
                        ctx.fill()
                        endLabels.push({ y: lastY, color: color, text: labelFn(lastV) })
                    }

                    drawSeries("fan", root.colFan, yRpm, v => Math.round(v) + "")
                    drawSeries("pad", root.colPad, yRpm, v => Math.round(v) + "")
                    drawSeries("gpu", root.colGpu, yTemp, v => Math.round(v) + "°")
                    drawSeries("tctl", root.colCpu, yTemp, v => Math.round(v) + "°")

                    // anti-collision : espacer les labels superposes
                    endLabels.sort((a, b) => a.y - b.y)
                    let prevY = -99
                    for (const lbl of endLabels) {
                        if (lbl.y < prevY + 11) lbl.y = prevY + 11
                        prevY = lbl.y
                    }
                    const labelX = mL + cw + 5
                    ctx.font = 'bold 10px ' + Application.font.family
                    for (const lbl of endLabels) {
                        ctx.fillStyle = lbl.color
                        ctx.fillText(lbl.text, labelX, lbl.y + 3)
                    }
                }
            }

            // -- separateur + controles ---------------------------------------
            Rectangle {
                visible: root.padVisible
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                implicitHeight: 1
                color: Kirigami.Theme.alternateBackgroundColor
            }

            RowLayout {
                visible: root.padVisible
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                PlasmaComponents.Label {
                    text: i18n("Contrôle du pad")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Switch {
                    checked: root.mode !== "libre"
                    onToggled: root.exec(root.helper + " mode " + (checked ? "silencieux" : "libre"))
                }
            }
            RowLayout {
                visible: root.padVisible && root.mode !== "libre"
                Layout.fillWidth: true
                PlasmaComponents.Label {
                    text: i18n("Mode jeu")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Switch {
                    checked: root.mode === "jeu"
                    onToggled: root.exec(root.helper + " mode " + (checked ? "jeu" : "silencieux"))
                }
            }
            RowLayout {
                visible: root.padVisible && root.mode !== "libre"
                Layout.fillWidth: true
                PlasmaComponents.Label {
                    text: i18n("Plateau mode jeu")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Label {
                    text: {
                        if (root.sliderBusy || plateauSlider.pressed)
                            return CLogic.snapPlateau(plateauSlider.value) + " RPM …"
                        return root.plateau >= 0
                                ? CLogic.snapPlateau(500 + root.plateau * 27) + " RPM · " + Math.round(root.plateau) + " %"
                                : "—"
                    }
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    font.weight: Font.Bold
                }
            }
            PlasmaComponents.Slider {
                id: plateauSlider
                // n'apparait qu'une fois la premiere donnee recue (pas de flash a la position 0)
                visible: root.padVisible && root.mode !== "libre" && root.polls > 0
                Layout.fillWidth: true
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                from: 500
                to: 3200
                stepSize: 300
                enabled: root.plateau >= 0
                // handle crantifie pendant le drag, pattern du slider Animation
                // speed de la landing page Plasma (kcms/landingpage) : SnapAlways
                // snape la position sur la grille des pas a chaque mouvement.
                // Le default du wrapper Plasma est SnapOnRelease (glissement
                // continu puis snap au relachement), d'ou la surcharge.
                snapMode: QQC2.Slider.SnapAlways

                // NB QQC2 : Slider n'expose ni onPressed ni onReleased comme
                // signaux (pressed est une propriete — bug vécu : handler
                // inexistant = plasmoid entier en fallback icone settings)
                onPressedChanged: {
                    if (pressed) {
                        root.sliderBusy = true
                    } else {
                        commitPlateau()
                        sliderLock.restart()
                    }
                }
                // molette et clavier : moved() hors drag = commit immediat
                onMoved: {
                    if (!pressed)
                        commitPlateau()
                }

                function commitPlateau() {
                    const cible = CLogic.snapPlateau(plateauSlider.value)
                    root.exec(root.helper + " set-plateau " + Math.round((cible - 500) / 27))
                }

                Timer {
                    id: sliderLock
                    interval: 4000
                    onTriggered: root.sliderBusy = false
                }

                Connections {
                    target: root
                    function onPlateauChanged() {
                        if (!root.sliderBusy && !plateauSlider.pressed && root.plateau >= 0)
                            plateauSlider.value = 500 + root.plateau * 27
                    }
                }

                // resync : si un drag a echoue au commit ou a ete interrompu,
                // le slider recolle sur le plateau reel dans les 5 s
                Timer {
                    interval: 5000
                    repeat: true
                    running: true
                    onTriggered: {
                        if (!root.sliderBusy && !plateauSlider.pressed && root.plateau >= 0)
                            plateauSlider.value = 500 + root.plateau * 27
                    }
                }
            }
        }
    }

    // Apercu panneau : GPU puis CPU (le % CPU suit, flot de lecture naturel),
    // separateurs discrets entre groupes, chat anime a droite (charge CPU,
    // frames CatWalk GPL-2.0+, (c) Yuri Saurov ; lignee RunCat (Takuto Nakamura)).
    // Clic explicite : Plasma ne declenche pas l'ouverture auto chez nous,
    // on bascule root.expanded (PlasmoidItem) a la main.
    compactRepresentation: Item {
        id: compact
        readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
        readonly property real h: Math.min(parent ? parent.height : 32, 48)

        // sizing panneau (pattern thermalmonitor) : le conteneur lit Layout.*
        Layout.preferredWidth: vertical ? -1 : compactRow.implicitWidth
        Layout.preferredHeight: vertical ? compactRow.implicitHeight : -1
        Layout.minimumWidth: compactRow.implicitWidth
        Layout.minimumHeight: compactRow.implicitHeight

        // declaration "bouton" standard (cf. DefaultCompactRepresentation du shell)
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: i18n("Cooling Control")
        Accessible.description: i18n("Ouvrir le panneau de refroidissement")
        Accessible.onPressAction: root.expanded = !root.expanded

        Keys.onPressed: event => {
            switch (event.key) {
            case Qt.Key_Space:
            case Qt.Key_Enter:
            case Qt.Key_Return:
            case Qt.Key_Select:
                root.expanded = !root.expanded
                event.accepted = true
                break
            }
        }

        RowLayout {
            id: compactRow
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.rightMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.largeSpacing

            // colonne GPU : label + temperature, charge dessous
            ColumnLayout {
                spacing: 0
                Layout.alignment: Qt.AlignVCenter
                RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    Layout.alignment: Qt.AlignHCenter
                    PlasmaComponents.Label {
                        Layout.alignment: Qt.AlignVCenter
                        text: i18n("GPU")
                        color: Kirigami.Theme.disabledTextColor
                        font.pixelSize: compact.h * 0.28
                    }
                    ColumnLayout {
                        spacing: 0
                        PlasmaComponents.Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: CLogic.gpuText(root.avgOf("gpu"), root.gpu)
                            color: Kirigami.Theme.textColor
                            font.pixelSize: compact.h * 0.42
                        }
                        PlasmaComponents.Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: CLogic.gpuLoadText(root.gpuLoad)
                            color: Kirigami.Theme.textColor
                            font.pixelSize: compact.h * 0.30
                        }
                    }
                }
            }

            Rectangle { Layout.alignment: Qt.AlignVCenter; implicitWidth: 1; implicitHeight: compact.h * 0.55; color: Kirigami.Theme.disabledTextColor; opacity: 0.4 }

            // colonne CPU : idem
            ColumnLayout {
                spacing: 0
                Layout.alignment: Qt.AlignVCenter
                RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    Layout.alignment: Qt.AlignHCenter
                    PlasmaComponents.Label {
                        Layout.alignment: Qt.AlignVCenter
                        text: i18n("CPU")
                        color: Kirigami.Theme.disabledTextColor
                        font.pixelSize: compact.h * 0.28
                    }
                    ColumnLayout {
                        spacing: 0
                        PlasmaComponents.Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: CLogic.tempText(root.avgOf("tctl"), root.tctl)
                            color: Kirigami.Theme.textColor
                            font.pixelSize: compact.h * 0.42
                        }
                        PlasmaComponents.Label {
                            Layout.alignment: Qt.AlignHCenter
                            text: CLogic.cpuText(root.cpu)
                            color: Kirigami.Theme.textColor
                            font.pixelSize: compact.h * 0.30
                        }
                    }
                }
            }

            // cadratin : le chat, seul
            Rectangle { Layout.alignment: Qt.AlignVCenter; implicitWidth: 1; implicitHeight: compact.h * 0.55; color: Kirigami.Theme.disabledTextColor; opacity: 0.4 }

            KSvg.SvgItem {
                id: catItem
                property int frame: 0
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: compact.h * 0.9
                Layout.preferredHeight: compact.h * 0.9
                imagePath: Qt.resolvedUrl("../images/my-idle-symbolic.svg")

                Timer {
                    id: catTimer
                    repeat: true
                    running: visible
                    interval: CLogic.catInterval(CLogic.driveLoad(root.cpu, root.gpuLoad))
                    onTriggered: {
                        if (CLogic.catIsIdle(CLogic.driveLoad(root.cpu, root.gpuLoad))) {
                            catItem.imagePath = Qt.resolvedUrl("../images/my-idle-symbolic.svg")
                        } else {
                            catItem.imagePath = Qt.resolvedUrl("../images/my-active-" + catItem.frame + "-symbolic.svg")
                            catItem.frame = CLogic.nextFrame(catItem.frame)
                        }
                    }
                }
            }
        }

        MouseArea {
            id: compactMouse
            property bool wasExpanded: false
            anchors.fill: parent
            hoverEnabled: true
            onPressed: wasExpanded = root.expanded
            onClicked: mouse => {
                if (mouse.button === Qt.MiddleButton) {
                    Plasmoid.secondaryActivated()
                } else {
                    root.expanded = !wasExpanded
                }
            }
        }
    }
}
