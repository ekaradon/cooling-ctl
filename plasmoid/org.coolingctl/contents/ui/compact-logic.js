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

// Slider grid of both floor sliders: 200 = the off position (one step
// below the pad's 500 RPM floor), then 500..3200 in 300-RPM steps.
// Off releases the pad (the daemon's off report): the fan rests instead
// of churning at the 500 RPM stall point.
const FLOOR_OFF_POS = 200

// true when a slider position is the off position (anything below the
// 500 step - half the distance to it, so the snap cannot jump back)
function isFloorOff(v) {
    return v <= 350
}

// Snaps an RPM/position onto the slider's step grid (300 steps, 200..3200).
// 200 = off (pad released), 500 = pad floor (0 %), 3200 = hardware max (100 %)
function snapFloor(rpm) {
    if (isFloorOff(rpm)) return FLOOR_OFF_POS
    const from = 500, to = 3200, step = 300
    const snapped = from + Math.round((rpm - from) / step) * step
    return Math.max(from, Math.min(to, snapped))
}

// Pad percent -> slider position, linear (the daemon's pct_to_rpm scale:
// 0 % = 500, 100 % = 3200). -2 = the wire sentinel for off (the floor
// is off, the pad is released) -> the off position. NOT snapped: display
// and commit round through snapFloor / floorArg themselves.
function pctToRpm(pct) {
    if (pct === -2) return FLOOR_OFF_POS
    return 500 + pct * 27
}

// Slider position -> helper argument: "off" (release) or the integer
// percent (what the helper's set-floor / set-default-floor verbs accept)
function floorArg(rpm) {
    if (isFloorOff(rpm)) return "off"
    return String(Math.round((snapFloor(rpm) - 500) / 27))
}

// Commanded RPM -> pad percent, rounded to an integer (inverse of
// pctToRpm's linear part — what the helper's set-floor verbs accept)
function rpmToPct(rpm) {
    return Math.round((rpm - 500) / 27)
}

// QML color object -> "#rrggbb" (drives the static LED color button)
function colorHex(c) {
    const to2 = function (v) {
        let n = Math.round(Math.max(0, Math.min(1, v)) * 255)
        return n.toString(16).padStart(2, "0")
    }
    return "#" + to2(c.r) + to2(c.g) + to2(c.b)
}
