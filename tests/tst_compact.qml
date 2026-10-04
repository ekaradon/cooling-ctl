import QtQuick
import QtTest
import "../plasmoid/org.coolingctl/contents/ui/compact-logic.js" as CL

// Tests of the compact (panel) view logic — qmltestrunner.
// Specifications:
//   S12 cat cadence: decreases with load, 80 ms floor,
//       formule CatWalk 5000/sqrt(cpu+35)-400
//   S13 idle threshold: idle < 20 %
//   S14 frame cycle: 5 frames, wraps to 0
//   S15 compact texts: average > instant > fallback (dash for CPU,
//       empty string for GPU)
TestCase {
    name: "compact"

    function test_s12_cadence() {
        verify(CL.catInterval(0) > CL.catInterval(50), "cadence must accelerate with load")
        verify(CL.catInterval(50) > CL.catInterval(100), "idem")
        compare(CL.catInterval(100), Math.max(80, Math.ceil(5000 / Math.sqrt(135) - 400)))
        verify(CL.catInterval(1000) >= 80, "plancher 80 ms")
    }

    function test_s12_charge_negative() {
        verify(CL.catInterval(-1) > 0, "charge aberrante : pas de crash")
    }

    function test_s13_idle() {
        verify(CL.catIsIdle(0))
        verify(CL.catIsIdle(19.9))
        verify(!CL.catIsIdle(20))
        verify(!CL.catIsIdle(100))
    }

    function test_s14_frames() {
        compare(CL.nextFrame(0), 1)
        compare(CL.nextFrame(4), 0)
        compare(CL.nextFrame(CL.nextFrame(CL.nextFrame(CL.nextFrame(CL.nextFrame(0))))), 0)
    }

    function test_s15_tempText() {
        compare(CL.tempText(71.6, 90), "72°")   // average takes priority, rounded
        compare(CL.tempText(-1, 90), "90°")     // instant fallback
        compare(CL.tempText(-1, -1), "—")       // no data
    }

    function test_s15_gpuText() {
        compare(CL.gpuText(44.2, 51), "44°")
        compare(CL.gpuText(-1, 51), "51°")
        compare(CL.gpuText(-1, -1), "")         // GPU: nothing rather than a dash
    }

    function test_s20_driveLoad() {
        compare(CL.driveLoad(13, 0), 13)      // GPU idle: CPU leads
        compare(CL.driveLoad(5, 97), 97)      // GPU loaded: it leads
        compare(CL.driveLoad(-1, -1), 0)      // invalid: idle
        compare(CL.driveLoad(50, 50), 50)
    }

    function test_s21_gpuLoadText() {
        compare(CL.gpuLoadText(97.4), "97 %")
        compare(CL.gpuLoadText(0), "0 %")
        compare(CL.gpuLoadText(-1), "")        // GPU absent: nothing
        compare(CL.gpuLoadText(NaN), "")
    }

    function test_s26_snapPlateau() {
        compare(CL.snapPlateau(500), 500)     // pad floor (0 %)
        compare(CL.snapPlateau(490), 500)     // below the bound: clamp
        compare(CL.snapPlateau(1688), 1700)   // continuous value -> nearest step
        compare(CL.snapPlateau(1623), 1700)
        compare(CL.snapPlateau(1391), 1400)
        compare(CL.snapPlateau(3200), 3200)   // hardware maximum (100 %)
        compare(CL.snapPlateau(3300), 3200)   // beyond: clamp
    }

    function test_s29_grille_paliers() {
        // fixed point of the native slider (from 500, to 3200, stepSize 300,
        // snapMode SnapAlways): every grid step is stable under
        // snapPlateau, the max lands exactly on the grid, and the 10
        // ticks stay <= 20 (above that the Plasma wrapper stops drawing them)
        for (let k = 0; k <= 9; k++)
            compare(CL.snapPlateau(500 + k * 300), 500 + k * 300, "palier " + k)
        verify((3200 - 500) % 300 === 0, "the max must land exactly on the grid")
        compare((3200 - 500) / 300, 9)
        verify((3200 - 500) / 300 <= 20, "above 20 steps the Plasma wrapper hides the ticks")
    }

    function test_s18_cpuText() {
        compare(CL.cpuText(42.3), "42 %")        // load rounded, discrete
        compare(CL.cpuText(0), "0 %")
        compare(CL.cpuText(100), "100 %")
        compare(CL.cpuText(-1), "")              // invalide : rien affiché
        compare(CL.cpuText(NaN), "")
    }
}
