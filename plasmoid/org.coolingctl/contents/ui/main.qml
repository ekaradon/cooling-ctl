import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as P5Support
import org.kde.kquickcontrols as KQuickControls
import "compact-logic.js" as CLogic

PlasmoidItem {
    id: root

    // current state
    property real tctl: -1
    property real gpu: -1
    property real fan: -1
    property real padRpm: -1
    property string mode: "?"
    property real floor: -1
    property real cpu: 0
    property real gpuLoad: -1
    property string led: "keep"
    property string ledColor: "#ff6600"   // last static color picked in the UI
    property int ledBright: -1             // configured LED brightness (from the status)
    property bool ledBusy: false          // 4 s lock after a lighting commit (optimistic update)
    property bool modeBusy: false         // 4 s lock after a mode commit (optimistic update)
    property int polls: 0
    property bool sliderBusy: false   // true during the drag + 4 s after (anti snap-back lock)

    // pad visible until the first sample arrives (avoids the startup flash),
    // then only if the pad answers
    readonly property bool padVisible: root.polls === 0 || root.padRpm >= 0

    // history: { tctl, gpu, fan, pad }
    property var history: []
    readonly property int maxPoints: 120
    readonly property real tempMax: 100
    readonly property real tempMin: 40
    readonly property real rpmMax: 6000

    readonly property string helper: Qt.resolvedUrl("../code/coolingctl.sh").toString().replace("file://", "")

    // series colors (stable across both Breeze themes)
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

    // average of a series over the chart's visible window (up to 4 min)
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
        // optimistic updates: while a commit's lock is held the poll keeps
        // the locally applied value; once released, the daemon's confirmed
        // state resyncs (and catches failed commits)
        if (!root.modeBusy)
            root.mode = p[4]
        root.floor = parseFloat(p[5])
        root.gpu = parseFloat(p[6])
        root.cpu = p.length > 7 ? parseFloat(p[7]) : 0
        root.gpuLoad = p.length > 8 ? parseFloat(p[8]) : -1
        if (!root.ledBusy) {
            root.led = p.length > 9 ? p[9] : "keep"
            root.ledBright = p.length > 10 ? parseInt(p[10]) : -1
            if (p.length > 11 && /^#[0-9a-fA-F]{6}$/.test(p[11]))
                root.ledColor = p[11]
        }

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

    // optimistic commit: apply locally, lock the poll out for 4 s, let the
    // daemon's confirmed state resync once the lock releases
    function commitMode(m) {
        root.mode = m
        root.modeBusy = true
        root.exec(root.helper + " mode " + m)
        modeLock.restart()
    }

    Timer {
        id: modeLock
        interval: 4000
        onTriggered: root.modeBusy = true
    }

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

            // tabs first (media-player plasmoid pattern — the popup opens
            // on its tabs, nothing above them); the spinner marks an
            // optimistic commit being applied by the daemon
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: -Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents.TabBar {
                    id: mainTabs
                    Layout.fillWidth: true
                    PlasmaComponents.TabButton { text: i18n("Cooling") }  // qmllint disable unqualified
                    PlasmaComponents.TabButton { text: i18n("Lighting") }  // qmllint disable unqualified
                }

                PlasmaComponents.BusyIndicator {
                    visible: root.modeBusy || root.ledBusy || root.sliderBusy  // qmllint disable unqualified
                    running: visible
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                    Layout.alignment: Qt.AlignVCenter
                    Accessible.name: i18n("Applying changes")  // qmllint disable unqualified
                }
            }

            // fixed-height page slot: the popup keeps its geometry across
            // tabs — the tab bar never moves, content is top-anchored
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

            // Cooling page: mode badge, stats, chart, fan controls
            ColumnLayout {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                visible: mainTabs.currentIndex === 0
                Layout.topMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                // mode badge: this is cooling state, it lives here
                RowLayout {
                    Layout.fillWidth: true
                    Layout.bottomMargin: -Kirigami.Units.smallSpacing

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        visible: root.padVisible  // qmllint disable unqualified
                        radius: height / 2
                        implicitHeight: modeLabel.implicitHeight + 2 * Kirigami.Units.smallSpacing
                        implicitWidth: modeLabel.implicitWidth + 3 * Kirigami.Units.smallSpacing
                        readonly property bool isGame: root.mode === "game"  // qmllint disable unqualified
                        color: isGame
                               ? Qt.rgba(Kirigami.Theme.highlightColor.r,
                                         Kirigami.Theme.highlightColor.g,
                                         Kirigami.Theme.highlightColor.b, 0.25)
                               : Kirigami.Theme.alternateBackgroundColor

                        PlasmaComponents.Label {
                            id: modeLabel
                            anchors.centerIn: parent
                            text: root.mode === "game" ? i18n("GAME MODE")  // qmllint disable unqualified
                             : root.mode === "free" ? i18n("FREE")  // qmllint disable unqualified
                             : i18n("SILENT CURVE")  // qmllint disable unqualified
                            color: parent.isGame ? Kirigami.Theme.highlightColor : Kirigami.Theme.disabledTextColor
                            font.pointSize: Application.font.pointSize * 0.75
                            font.letterSpacing: 1
                            font.weight: Font.DemiBold
                        }
                    }
                }

                // -- stats: CPU + GPU heroes, RPM secondary ----------------
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing * 3

                ColumnLayout {
                    spacing: 0
                    Layout.alignment: Qt.AlignVCenter

                    PlasmaComponents.Label {
                        text: root.tctl >= 0 ? root.tctl.toFixed(0) + "°" : "—"  // qmllint disable unqualified
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2.8
                        font.weight: Font.Black
                        color: root.colCpu  // qmllint disable unqualified
                    }
                    PlasmaComponents.Label {
                        text: root.avgOf("tctl") >= 0 ? i18n("%1° avg.", Math.round(root.avgOf("tctl"))) : ""  // qmllint disable unqualified
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.75)
                        font.weight: Font.Bold
                        color: root.colCpu  // qmllint disable unqualified
                    }
                    PlasmaComponents.Label {
                        text: i18n("CPU · TCTL")  // qmllint disable unqualified
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                        font.letterSpacing: 1
                        color: Kirigami.Theme.disabledTextColor
                    }
                }

                ColumnLayout {
                    spacing: 0
                    Layout.alignment: Qt.AlignVCenter
                    PlasmaComponents.Label {
                        text: root.gpu >= 0 ? root.gpu.toFixed(0) + "°" : "—"  // qmllint disable unqualified
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2.8
                        font.weight: Font.Black
                        color: root.colGpu  // qmllint disable unqualified
                    }
                    PlasmaComponents.Label {
                        text: root.avgOf("gpu") >= 0 ? i18n("%1° avg.", Math.round(root.avgOf("gpu"))) : ""  // qmllint disable unqualified
                        font.pixelSize: Math.round(Application.font.pixelSize * 0.75)
                        font.weight: Font.Bold
                        color: root.colGpu  // qmllint disable unqualified
                    }
                    PlasmaComponents.Label {
                        text: i18n("GPU")  // qmllint disable unqualified
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

                    PlasmaComponents.Label { text: i18n("Laptop fans"); font.pixelSize: Math.round(Application.font.pixelSize * 0.85); color: Kirigami.Theme.disabledTextColor }  // qmllint disable unqualified
                    PlasmaComponents.Label {
                        Layout.alignment: Qt.AlignRight
                        text: root.fan >= 0 ? Math.round(root.fan) : "—"  // qmllint disable unqualified
                        font.weight: Font.Bold
                        color: root.colFan  // qmllint disable unqualified
                    }
                    PlasmaComponents.Label { text: i18n("Pad fan"); visible: root.padVisible; font.pixelSize: Math.round(Application.font.pixelSize * 0.85); color: Kirigami.Theme.disabledTextColor }  // qmllint disable unqualified
                    PlasmaComponents.Label {
                        visible: root.padVisible  // qmllint disable unqualified
                        Layout.alignment: Qt.AlignRight
                        text: root.padRpm >= 0 ? Math.round(root.padRpm) : "—"  // qmllint disable unqualified
                        font.weight: Font.Bold
                        color: root.colPad  // qmllint disable unqualified
                    }
                }
            }

            // -- chart --------------------------------------------------------
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

                    // discrete grid: reference lines only
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
                    // axis titles
                    ctx.font = 'bold 8px ' + Application.font.family
                    ctx.fillText("°C", 2, 9)
                    ctx.textAlign = "right"
                    ctx.fillText("RPM", W - 4, 9)
                    ctx.textAlign = "left"
                    ctx.font = '9px ' + Application.font.family
                    // threshold band: area above 93 degrees tinted
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
                        ctx.fillText(i18n("collecting data…"), mL + cw / 2, mT + ch / 2)
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
                        // endpoint dot + current value (label resolved later, anti-collision)
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

                    // anti-collision: spread overlapping labels
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

            // -- separator + controls ---------------------------------------
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
                    text: i18n("Pad control")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Switch {
                    checked: root.mode !== "free"
                    onToggled: root.commitMode(checked ? "silent" : "free")
                }
            }
            RowLayout {
                visible: root.padVisible && root.mode !== "free"
                Layout.fillWidth: true
                PlasmaComponents.Label {
                    text: i18n("Game mode")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Switch {
                    checked: root.mode === "game"
                    onToggled: root.commitMode(checked ? "game" : "silent")
                }
            }
            RowLayout {
                visible: root.padVisible && root.mode !== "free"
                Layout.fillWidth: true
                PlasmaComponents.Label {
                    text: i18n("Game mode minimum RPM")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Label {
                    text: {
                        if (root.sliderBusy || floorSlider.pressed)
                            return CLogic.snapFloor(floorSlider.value) + " RPM …"
                        return root.floor >= 0
                                ? CLogic.snapFloor(500 + root.floor * 27) + " RPM · " + Math.round(root.floor) + " %"
                                : "—"
                    }
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    font.weight: Font.Bold
                }
            }
            PlasmaComponents.Slider {
                id: floorSlider
                // only shows once the first data point arrives (no flash at position 0)
                visible: root.padVisible && root.mode !== "free" && root.polls > 0
                Layout.fillWidth: true
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                from: 500
                to: 3200
                stepSize: 300
                enabled: root.floor >= 0
                // handle snapped while dragging, the pattern of the Animation speed
                // slider of Plasma's landing page (kcms/landingpage): SnapAlways
                // snaps the position onto the step grid on every move.
                // The Plasma wrapper default is SnapOnRelease (continuous
                // slide then snap on release), hence the override.
                snapMode: QQC2.Slider.SnapAlways

                // QQC2 note: Slider exposes neither onPressed nor onReleased as
                // signals (pressed is a property — lived bug: a handler on a
                // non-existent signal kills the whole plasmoid, settings-icon fallback)
                onPressedChanged: {
                    if (pressed) {
                        root.sliderBusy = true
                    } else {
                        commitFloor()
                        sliderLock.restart()
                    }
                }
                // wheel and keyboard: moved() outside a drag = immediate commit
                onMoved: {
                    if (!pressed)
                        commitFloor()
                }

                function commitFloor() {
                    const cible = CLogic.snapFloor(floorSlider.value)
                    root.exec(root.helper + " set-floor " + Math.round((cible - 500) / 27))
                }

                Timer {
                    id: sliderLock
                    interval: 4000
                    onTriggered: root.sliderBusy = false
                }

                Connections {
                    target: root
                    function onFloorChanged() {
                        if (!root.sliderBusy && !floorSlider.pressed && root.floor >= 0)
                            floorSlider.value = 500 + root.floor * 27
                    }
                }

                // resync: if a drag failed to commit or was interrupted,
                // the slider snaps back to the real floor within 5 s
                Timer {
                    interval: 5000
                    repeat: true
                    running: true
                    onTriggered: {
                        if (!root.sliderBusy && !floorSlider.pressed && root.floor >= 0)
                            floorSlider.value = 500 + root.floor * 27
                    }
                }
            }

            }

            // Lighting page: LED effect, brightness, color picker
            ColumnLayout {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                visible: mainTabs.currentIndex === 1
                Layout.topMargin: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                // LED strip: effect, brightness, static color picker (inline,
                // no OS dialog — ColorDialog does not behave in a plasmoid popup)
            RowLayout {
                visible: root.padVisible
                Layout.fillWidth: true
                PlasmaComponents.Label {
                    text: i18n("LED")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.ComboBox {
                    id: ledSelect
                    // disabled until the daemon's configured effect is known:
                    // never offer a control showing a value we don't have yet
                    enabled: root.polls > 0
                    readonly property var values: ["keep", "off", "static", "spectrum", "wave", "heat"]
                    model: [i18n("Default"), i18n("Off"), i18n("Static"), i18n("Spectrum"), i18n("Wave"), i18n("Heat")]
                    currentIndex: Math.max(0, values.indexOf(root.led))
                    onActivated: function(index) {
                        root.led = values[index]     // optimistic
                        root.ledBusy = true
                        root.exec(root.helper + " led " + values[index])
                        ledLock.restart()
                    }
                }
            }

            // mode description: a light framed note explaining the current
            // effect, so "Heat" or "Wave" are not guessing games
            Rectangle {
                visible: root.padVisible
                Layout.fillWidth: true
                radius: Kirigami.Units.smallSpacing
                color: "transparent"
                border.color: Kirigami.Theme.disabledTextColor
                border.width: 1
                opacity: 0.75
                implicitHeight: ledModeDesc.height + 2 * Kirigami.Units.largeSpacing

                PlasmaComponents.Label {
                    id: ledModeDesc
                    // explicit geometry (no anchors): with an explicit width
                    // and wrapMode the label derives its own wrapped height;
                    // uniform largeSpacing padding inside the frame
                    x: Kirigami.Units.largeSpacing
                    y: Kirigami.Units.largeSpacing
                    width: parent.width - 2 * Kirigami.Units.largeSpacing
                    wrapMode: Text.WordWrap
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    // real explanatory text uses the real text color —
                    // disabledTextColor is for disabled controls, not prose
                    color: Kirigami.Theme.textColor
                    text: {
                        switch (root.led) {
                        case "off":      return i18n("Turn the LED strip off entirely.")
                        case "static":  return i18n("A single fixed color at the chosen brightness. Pick the color with the button below.")
                        case "spectrum": return i18n("The strip cycles continuously through the whole color wheel.")
                        case "wave":    return i18n("A wave of light travels along the strip, from left to right.")
                        case "heat":    return i18n("The strip becomes a thermal gauge: color and brightness follow the CPU temperature — green and dim when cool, red and fully bright in the danger zone around 93 °C.")
                        default:        return i18n("Leave the pad's lighting untouched: no LED command is ever sent, the pad keeps its factory behavior.")
                        }
                    }
                }
            }
                // brightness: label row above, full-width slider below —
                // the cooling tab convention; hidden in heat mode (the
                // daemon drives the brightness with the temperature there)
                ColumnLayout {
                    visible: root.padVisible && root.led !== "keep" && root.led !== "heat"
                    Layout.fillWidth: true
                    spacing: 0

                    RowLayout {
                        Layout.fillWidth: true
                        PlasmaComponents.Label {
                            text: i18n("Brightness")
                            font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                            color: Kirigami.Theme.disabledTextColor
                        }
                        Item { Layout.fillWidth: true }
                        PlasmaComponents.Label {
                            // ellipsis until the daemon reports the real
                            // brightness: never show a fake "0 %"
                            text: root.ledBright >= 0 ? ledBrightness.value + " %" : i18n("…")
                            font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                            font.weight: Font.Bold
                        }
                    }

                        PlasmaComponents.Slider {
                        id: ledBrightness
                        from: 0; to: 100; stepSize: 5
                        // disabled until the daemon reports the configured
                        // brightness — dragging a placeholder value would
                        // commit garbage
                        enabled: root.ledBright >= 0
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        // initialized from the daemon's configured brightness;
                        // held while dragging AND for 4 s after the commit
                        // (the status keeps the old value until the daemon
                        // reloads — without the lock the thumb flickers back).
                        // NB: imperative resync only, never a conditional
                        // `Binding` on `value` — when the `when` clause goes
                        // false (ledBusy latch on an effect commit) QML
                        // RESTORES the value the property had before the
                        // binding activated, here the slider default 0:
                        // the thumb flashed to 0 % on every effect change
                        // (lived bug 2026-10-05).
                        Connections {
                            target: root
                            function onLedBrightChanged() {
                                if (!ledBrightness.pressed && !root.ledBusy && root.ledBright >= 0)
                                    ledBrightness.value = root.ledBright
                            }
                        }
                        // resync: if a brightness drag failed to commit, the
                        // thumb snaps back to the daemon's value within 5 s
                        Timer {
                            interval: 5000
                            repeat: true
                            running: true
                            onTriggered: {
                                if (!ledBrightness.pressed && !root.ledBusy && root.ledBright >= 0)
                                    ledBrightness.value = root.ledBright
                            }
                        }
                        onPressedChanged: {
                            if (!pressed) {
                                root.ledBusy = true
                                root.exec(root.helper + " led bright " + value)
                                ledLock.restart()
                            }
                        }
                        Timer {
                            id: ledLock
                            interval: 4000
                            onTriggered: root.ledBusy = false
                        }
                    }
                }

            // static color: KDE's native color button (opens the standard
            // color dialog — wheel, hex, pipette; no hand-rolled picker)
            RowLayout {
                visible: root.padVisible && root.led === "static"
                Layout.fillWidth: true
                PlasmaComponents.Label {
                    text: i18n("Color")
                    font.pixelSize: Math.round(Application.font.pixelSize * 0.85)
                    color: Kirigami.Theme.disabledTextColor
                }
                Item { Layout.fillWidth: true }
                KQuickControls.ColorButton {
                    showAlphaChannel: false
                    color: root.ledColor
                    onAccepted: function(c) {
                        root.ledColor = CLogic.colorHex(c)   // optimistic
                        root.ledBusy = true
                        ledLock.restart()
                        // NB: the hex is sent WITHOUT the leading '#' — through
                        // the exec transport a raw '#' starts a shell comment
                        root.exec(root.helper + " led static " + root.ledColor.slice(1))
                    }
                }
            }
            }
            }
        }
    }

    // Panel view: GPU then CPU (CPU % follows, natural reading flow),
    // discrete separators between groups, animated cat on the right (CPU load,
    // CatWalk frames GPL-2.0+, (c) Yuri Saurov; art lineage RunCat (Takuto Nakamura)).
    // Explicit click: Plasma does not trigger auto-open for us,
    // we flip root.expanded (PlasmoidItem) manually.
    compactRepresentation: Item {
        id: compact
        readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
        readonly property real h: Math.min(parent ? parent.height : 32, 48)

        // panel sizing (thermalmonitor pattern): the container reads Layout.*
        Layout.preferredWidth: vertical ? -1 : compactRow.implicitWidth
        Layout.preferredHeight: vertical ? compactRow.implicitHeight : -1
        Layout.minimumWidth: compactRow.implicitWidth
        Layout.minimumHeight: compactRow.implicitHeight

        // standard "button" declaration (cf. the shell's DefaultCompactRepresentation)
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: i18n("Cooling Control")
        Accessible.description: i18n("Open the cooling panel")
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

            // GPU column: label + temperature, load below
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

            // CPU column: same
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

            // em space: the cat, alone
            Rectangle { Layout.alignment: Qt.AlignVCenter; implicitWidth: 1; implicitHeight: compact.h * 0.55; color: Kirigami.Theme.disabledTextColor; opacity: 0.4 }

            // theme-colored silhouette: KSvg does not recolor symbolic SVGs
            // outside of an applet context (lived bug: black cat on dark)
            Kirigami.Icon {
                id: catItem
                property int frame: 0
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: compact.h * 0.9
                Layout.preferredHeight: compact.h * 0.9
                isMask: true
                color: Kirigami.Theme.textColor
                source: Qt.resolvedUrl("../images/my-idle-symbolic.svg")

                Timer {
                    id: catTimer
                    repeat: true
                    running: visible
                    interval: CLogic.catInterval(CLogic.driveLoad(root.cpu, root.gpuLoad))
                    onTriggered: {
                        if (CLogic.catIsIdle(CLogic.driveLoad(root.cpu, root.gpuLoad))) {
                            catItem.source = Qt.resolvedUrl("../images/my-idle-symbolic.svg")
                        } else {
                            catItem.source = Qt.resolvedUrl("../images/my-active-" + catItem.frame + "-symbolic.svg")
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
