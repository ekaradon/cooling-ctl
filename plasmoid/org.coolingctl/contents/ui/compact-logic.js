// Pure logic of the compact (panel) view — tested by tests/tst_compact.qml.
// Cat: frames and pacing taken from CatWalk (Yuri Saurov, GPL-2.0+);
// art lineage: RunCat (Takuto Nakamura).
.pragma library

// animation cadence from the CPU load (ms)
function catInterval(cpu) {
    return Math.max(80, Math.ceil(5000 / Math.sqrt(cpu + 35) - 400))
}

// idle threshold: idle frame below 20 %
function catIsIdle(cpu) {
    return cpu < 20
}

// 5-frame running cycle
function nextFrame(frame) {
    return (frame + 1) % 5
}

// CPU temperature text: window average, else instant, else dash
function tempText(avg, instant) {
    if (avg >= 0) return Math.round(avg) + "°"
    if (instant >= 0) return Math.round(instant) + "°"
    return "—"
}

// GPU temperature text: same, but nothing when there is no data
function gpuText(avg, instant) {
    if (avg >= 0) return Math.round(avg) + "°"
    if (instant >= 0) return Math.round(instant) + "°"
    return ""
}

// the cat's driving load: the highest of both activities
// (the cat runs at the pace of the busiest component)
function driveLoad(cpu, gpu) {
    const c = (cpu >= 0 && !isNaN(cpu)) ? cpu : 0
    const g = (gpu >= 0 && !isNaN(gpu)) ? gpu : 0
    return Math.max(c, g)
}

// CPU load text: discrete percentage, nothing when invalid
function cpuText(cpu) {
    if (cpu < 0 || isNaN(cpu)) return ""
    return Math.round(cpu) + " %"
}

// GPU load text: same
function gpuLoadText(gpu) {
    if (gpu < 0 || isNaN(gpu)) return ""
    return Math.round(gpu) + " %"
}

// Snaps an RPM onto the slider's step grid (300 steps, 500..3200).
// 500 = pad floor (0 %), 3200 = hardware maximum (100 %)
function snapFloor(rpm) {
    const from = 500, to = 3200, step = 300
    const snapped = from + Math.round((rpm - from) / step) * step
    return Math.max(from, Math.min(to, snapped))
}

// QML color object -> "#rrggbb" (drives the static LED color button)
function colorHex(c) {
    const to2 = function (v) {
        let n = Math.round(Math.max(0, Math.min(1, v)) * 255)
        return n.toString(16).padStart(2, "0")
    }
    return "#" + to2(c.r) + to2(c.g) + to2(c.b)
}
