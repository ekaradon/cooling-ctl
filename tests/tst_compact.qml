import QtQuick
import QtTest
import "../plasmoid/org.coolingctl/contents/ui/compact-logic.js" as CL

// Tests de la logique de l'aperçu compact (panneau) — qmltestrunner.
// Spécifications :
//   S12 cadence du chat : décroissante avec la charge, plancher 80 ms,
//       formule CatWalk 5000/sqrt(cpu+35)-400
//   S13 seuil d'inactivité : idle < 20 %
//   S14 cycle des frames : 5 frames, retour à 0
//   S15 textes compact : moyenne > instantané > défaut (tiret pour CPU,
//       chaîne vide pour GPU)
TestCase {
    name: "compact"

    function test_s12_cadence() {
        verify(CL.catInterval(0) > CL.catInterval(50), "la cadence doit accelérer avec la charge")
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
        compare(CL.tempText(71.6, 90), "72°")   // moyenne prioritaire, arrondie
        compare(CL.tempText(-1, 90), "90°")     // repli instantané
        compare(CL.tempText(-1, -1), "—")       // aucune donnée
    }

    function test_s15_gpuText() {
        compare(CL.gpuText(44.2, 51), "44°")
        compare(CL.gpuText(-1, 51), "51°")
        compare(CL.gpuText(-1, -1), "")         // GPU : rien plutôt que tiret
    }

    function test_s20_driveLoad() {
        compare(CL.driveLoad(13, 0), 13)      // GPU idle : le CPU mène
        compare(CL.driveLoad(5, 97), 97)      // GPU chargé : il mène
        compare(CL.driveLoad(-1, -1), 0)      // invalide : repos
        compare(CL.driveLoad(50, 50), 50)
    }

    function test_s21_gpuLoadText() {
        compare(CL.gpuLoadText(97.4), "97 %")
        compare(CL.gpuLoadText(0), "0 %")
        compare(CL.gpuLoadText(-1), "")        // GPU absent : rien
        compare(CL.gpuLoadText(NaN), "")
    }

    function test_s26_snapPlateau() {
        compare(CL.snapPlateau(500), 500)     // plancher du pad (0 %)
        compare(CL.snapPlateau(490), 500)     // sous la borne : clamp
        compare(CL.snapPlateau(1688), 1700)   // valeur continue -> palier le plus proche
        compare(CL.snapPlateau(1623), 1700)
        compare(CL.snapPlateau(1391), 1400)
        compare(CL.snapPlateau(3200), 3200)   // maximum materiel (100 %)
        compare(CL.snapPlateau(3300), 3200)   // au-dela : clamp
    }

    function test_s29_grille_paliers() {
        // point fixe du slider natif (from 500, to 3200, stepSize 300,
        // snapMode SnapAlways) : chaque palier de la grille est stable par
        // snapPlateau, le max tombe exactement sur la grille, et les 10
        // crans restent <= 20 (sinon le wrapper Plasma ne les dessine pas)
        for (let k = 0; k <= 9; k++)
            compare(CL.snapPlateau(500 + k * 300), 500 + k * 300, "palier " + k)
        verify((3200 - 500) % 300 === 0, "le max doit tomber exactement sur la grille")
        compare((3200 - 500) / 300, 9)
        verify((3200 - 500) / 300 <= 20, "au-dela de 20 pas le wrapper Plasma masque les crans")
    }

    function test_s18_cpuText() {
        compare(CL.cpuText(42.3), "42 %")        // charge arrondie, discret
        compare(CL.cpuText(0), "0 %")
        compare(CL.cpuText(100), "100 %")
        compare(CL.cpuText(-1), "")              // invalide : rien affiché
        compare(CL.cpuText(NaN), "")
    }
}
