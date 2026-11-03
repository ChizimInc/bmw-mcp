import csv
import json
import tempfile
import unittest
from pathlib import Path

from bmwdiag import guard
from bmwdiag.sources import FakeSource, ReplaySource


class Ceas:
    """Ceas controlat de test."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def fake(ceas, **kw):
    kw.setdefault("latenta_ms", 0)
    return FakeSource(ceas=ceas, **kw)


class TestFakeSource(unittest.TestCase):
    def test_valori_plauzibile_si_unitati(self):
        ceas = Ceas()
        with fake(ceas) as f:
            r = f.run("STATUS_MESSWERTE")
            self.assertTrue(r.ok)
            v = r.valori()
            self.assertTrue(1000 < v["STAT_NMOT_WERT"] < 1200)       # ralanti accelerat la rece
            self.assertAlmostEqual(v["STAT_TMOT_WERT"], 30, delta=0.5)
            self.assertEqual(v["STAT_NMOT_EINH"], "1/min")
            self.assertTrue(13.5 < v["STAT_UB_WERT"] < 14.5)
            self.assertIn("STAT_RL_WERT", f.run("STATUS_FASTA2").valori())  # sarcina

    def test_temperatura_creste(self):
        ceas = Ceas()
        with fake(ceas, perioada_cuplare_s=0) as f:
            temp = []
            for _ in range(6):
                temp.append(f.run("STATUS_MESSWERTE", "STAT_TMOT_WERT").valori()["STAT_TMOT_WERT"])
                ceas.t += 300
            self.assertEqual(temp, sorted(temp))
            self.assertGreater(temp[-1], 80)
            rpm = f.run("STATUS_MESSWERTE", "STAT_NMOT_WERT").valori()["STAT_NMOT_WERT"]
            self.assertTrue(650 < rpm < 760)                           # ralanti cald

    def _cadere(self, f, ceas):
        ceas.t += 1
        inainte = f.run("STATUS_MESSWERTE", "STAT_NMOT_WERT").valori()["STAT_NMOT_WERT"]
        f.cupleaza()
        ceas.t += 0.5                                                  # fundul caderii
        jos = f.run("STATUS_MESSWERTE", "STAT_NMOT_WERT").valori()["STAT_NMOT_WERT"]
        ceas.t += 3                                                    # revenire
        dupa = f.run("STATUS_MESSWERTE", "STAT_NMOT_WERT").valori()["STAT_NMOT_WERT"]
        self.assertAlmostEqual(dupa, inainte, delta=25)
        return inainte - jos

    def test_cadere_la_cuplare_mai_mare_la_cald(self):
        ceas = Ceas()
        with fake(ceas, perioada_cuplare_s=0) as f:
            rece = self._cadere(f, ceas)
            ceas.t += 3600
            cald = self._cadere(f, ceas)
        self.assertTrue(90 < rece < 150, rece)     # sub pragul de 150 din profil
        self.assertGreater(cald, 150)              # peste prag: steagul trebuie sa apara
        self.assertGreater(cald, rece)

    def test_cuplare_periodica(self):
        ceas = Ceas()
        with fake(ceas, perioada_cuplare_s=20) as f:
            ceas.t += 10
            self.assertFalse(f.stare()["cuplare"])
            ceas.t += 10.4
            self.assertTrue(f.stare()["cuplare"])

    def test_filtru(self):
        with fake(Ceas()) as f:
            r = f.run("STATUS_MESSWERTE", "STAT_NMOT_WERT;stat_tmot_wert")
        self.assertEqual(set(r.valori()), {"STAT_NMOT_WERT", "STAT_TMOT_WERT"})
        self.assertEqual(r.status, "OKAY")

    def test_determinist(self):
        a = [fake(Ceas(), seed=7) for _ in range(2)]
        for f in a:
            f.start()
        self.assertEqual(a[0].run("STATUS_MESSWERTE").valori(), a[1].run("STATUS_MESSWERTE").valori())

    def test_erori_si_detaliu(self):
        with fake(Ceas()) as f:
            r = f.run("FS_LESEN")
            self.assertTrue(r.ok)
            self.assertEqual(r.seturi[0]["F_HEX_CODE"], "hex:2b6388")
            self.assertEqual(r.seturi[-1], {"JOB_STATUS": "OKAY"})
            d = f.run("FS_LESEN_DETAIL", parametri="11107")
            self.assertTrue(d.ok)
            self.assertEqual(len(d.seturi), 3)          # eroare + al doilea rand de conditii + JOB_STATUS
            self.assertIn("JOB_MESSAGE", d.seturi[-1])
            self.assertFalse(f.run("FS_LESEN_DETAIL", parametri="1").ok)
            f.adauga_eroare(10700, "noua (simulat)")
            self.assertEqual([s["F_ORT_NR"] for s in f.run("FS_LESEN").seturi[:-1]], [11107, 10700])

    def test_job_nesimulat_si_garda(self):
        with fake(Ceas()) as f:
            r = f.run("STATUS_KVA")
            self.assertFalse(r.ok)
            self.assertIn("NOT_SUPPORTED", r.eroare)
            for job in ("FS_LOESCHEN", "STEUERN_EKP", "SET_X", "FLASH_LESEN"):
                with self.assertRaises(guard.JobBlocat):
                    f.run(job)

    def test_deconectat_si_rata_eroare(self):
        with fake(Ceas(), rata_eroare=1.0) as f:
            self.assertIn("IFH-0009", f.run("STATUS_MESSWERTE").eroare)
        with fake(Ceas()) as f:
            f.deconectat = True
            self.assertIn("IFH-0018", f.run("STATUS_MESSWERTE").eroare)
            f.deconectat = False
            self.assertTrue(f.run("STATUS_MESSWERTE").ok)
        self.assertFalse(fake(Ceas()).run("STATUS_MESSWERTE").ok)  # nepornit

    def test_latenta(self):
        with FakeSource(latenta_ms=30) as f:
            self.assertGreaterEqual(f.run("STATUS_UBATT").durata_ms, 25)


class TestReplaySource(unittest.TestCase):
    COLOANE = {
        "rpm": {"job": "STATUS_MESSWERTE", "rezultat": "STAT_NMOT_WERT", "unitate": "1/min"},
        "tmot": {"job": "STATUS_MESSWERTE", "rezultat": "STAT_TMOT_WERT", "unitate": "Grad C"},
        "lu1": {"job": "STATUS_LAUFUNRUHE", "rezultat": "STAT_LUTSFI1_WERT", "unitate": "1/s"},
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scrie(self, nume, randuri, antet=("t_iso", "t_rel_s", "ciclu", "rpm", "tmot", "lu1")):
        with open(self.dir / nume, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(antet)
            w.writerows(randuri)

    def test_sesiune_cu_segmente(self):
        self.scrie("date_001.csv", [("x", "0.0", "1", "1100", "30", "-2.5"), ("x", "0.3", "2", "1090", "30.5", "")])
        self.scrie("date_002.csv", [("x", "0.6", "3", "900", "31", "")])
        (self.dir / "coloane.json").write_text(json.dumps(self.COLOANE), encoding="utf-8")
        with ReplaySource(self.dir) as r:
            r.ciclu_nou()
            v = r.run("STATUS_MESSWERTE").valori()
            self.assertEqual(v["STAT_NMOT_WERT"], 1100.0)
            self.assertEqual(v["STAT_NMOT_EINH"], "1/min")
            self.assertEqual(r.run("STATUS_LAUFUNRUHE").valori()["STAT_LUTSFI1_WERT"], -2.5)
            r.ciclu_nou()
            lu = r.run("STATUS_LAUFUNRUHE", "STAT_LUTSFI1_WERT")
            self.assertTrue(lu.ok)
            self.assertEqual(lu.valori(), {})                     # celula goala: grup necitit
            r.ciclu_nou()
            self.assertEqual(r.run("STATUS_MESSWERTE", "STAT_NMOT_WERT").valori(), {"STAT_NMOT_WERT": 900.0})
            r.ciclu_nou()
            self.assertTrue(r.epuizat)
            self.assertIn("sfarsitul", r.run("STATUS_MESSWERTE").eroare)

    def test_primul_run_fara_ciclu_nou_citeste_randul_0(self):
        self.scrie("a.csv", [("x", "0", "1", "1100", "30", "")])
        with ReplaySource(self.dir / "a.csv", coloane=self.COLOANE) as r:
            self.assertEqual(r.run("STATUS_MESSWERTE").valori()["STAT_NMOT_WERT"], 1100.0)

    def test_csv_vechi_cu_mapare(self):
        # formatul din bmw-data/2026-11-01_etapa2 (fara t_rel_s, alte nume)
        self.scrie("vechi.csv", [("16:47", "30.75", "1096.75")], antet=("ora", "tmot_C", "rpm"))
        cols = {"rpm": {"job": "STATUS_MESSWERTE", "rezultat": "STAT_NMOT_WERT"},
                "tmot_C": {"job": "STATUS_MESSWERTE", "rezultat": "STAT_TMOT_WERT"}}
        with ReplaySource(self.dir / "vechi.csv", coloane=cols, viteza=1) as r:
            r.ciclu_nou()
            v = r.run("STATUS_MESSWERTE").valori()
        self.assertEqual((v["STAT_NMOT_WERT"], v["STAT_TMOT_WERT"]), (1096.75, 30.75))

    def test_job_absent_si_garda(self):
        self.scrie("a.csv", [("x", "0", "1", "1100", "30", "")])
        with ReplaySource(self.dir / "a.csv", coloane=self.COLOANE) as r:
            self.assertFalse(r.run("STATUS_VVT").ok)
            with self.assertRaises(guard.JobBlocat):
                r.run("FS_LOESCHEN")
        rau = {"x": {"job": "STEUERN_EKP", "rezultat": "A"}}
        with self.assertRaises(guard.JobBlocat):
            ReplaySource(self.dir / "a.csv", coloane=rau)

    def test_fara_coloane_json(self):
        self.scrie("a.csv", [("x", "0", "1", "1100", "30", "")])
        with self.assertRaises(FileNotFoundError):
            ReplaySource(self.dir / "a.csv")

    def test_timp_real(self):
        import time
        self.scrie("a.csv", [("x", "0.0", "1", "1", "1", ""), ("x", "0.2", "2", "1", "1", "")])
        with ReplaySource(self.dir / "a.csv", coloane=self.COLOANE, viteza=1) as r:
            t0 = time.monotonic()
            r.ciclu_nou()
            r.ciclu_nou()
            self.assertGreaterEqual(time.monotonic() - t0, 0.18)


if __name__ == "__main__":
    unittest.main()
