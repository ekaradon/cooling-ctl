// Logique pure de l'aperçu compact (panneau) — testée par tests/tst_compact.qml.
// Chat : frames et cadence repris de CatWalk (Yuri Saurov, GPL-2.0+) ;
// lignee des dessins : RunCat (Takuto Nakamura).
.pragma library

// cadence d'animation en fonction de la charge CPU (ms)
function catInterval(cpu) {
    return Math.max(80, Math.ceil(5000 / Math.sqrt(cpu + 35) - 400))
}

// seuil d'inactivité : frame idle sous 20 %
function catIsIdle(cpu) {
    return cpu < 20
}

// cycle des 5 frames de course
function nextFrame(frame) {
    return (frame + 1) % 5
}

// texte temperature CPU : moyenne de fenetre, sinon instantanee, sinon tiret
function tempText(avg, instant) {
    if (avg >= 0) return Math.round(avg) + "°"
    if (instant >= 0) return Math.round(instant) + "°"
    return "—"
}

// texte temperature GPU : idem, mais rien si aucune donnee
function gpuText(avg, instant) {
    if (avg >= 0) return Math.round(avg) + "°"
    if (instant >= 0) return Math.round(instant) + "°"
    return ""
}

// charge motrice du chat : la plus haute des deux activites
// (le chat court au rythme du composant le plus occupe)
function driveLoad(cpu, gpu) {
    const c = (cpu >= 0 && !isNaN(cpu)) ? cpu : 0
    const g = (gpu >= 0 && !isNaN(gpu)) ? gpu : 0
    return Math.max(c, g)
}

// texte charge CPU : pourcentage discret, rien si donnee invalide
function cpuText(cpu) {
    if (cpu < 0 || isNaN(cpu)) return ""
    return Math.round(cpu) + " %"
}

// texte charge GPU : idem
function gpuLoadText(gpu) {
    if (gpu < 0 || isNaN(gpu)) return ""
    return Math.round(gpu) + " %"
}

// quantifie un RPM sur la grille des paliers du slider (pas de 300, 500..3200).
// 500 = plancher du pad (0 %), 3200 = maximum materiel (100 %)
function snapPlateau(rpm) {
    const from = 500, to = 3200, step = 300
    const snapped = from + Math.round((rpm - from) / step) * step
    return Math.max(from, Math.min(to, snapped))
}
