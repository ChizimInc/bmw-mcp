import json
import tempfile
import time
import unittest
from pathlib import Path

from bmwdiag import profiles, sesiuni
from bmwdiag.jurnal import Jurnal
from bmwdiag.recorder import DIR_DATE, Recorder
from bmwdiag.sources import FakeSource


class TestSesiuni(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.id1, cls.f1 = cls._inregistreaza(profiles.incarca("eveniment_rapid"))
        p = profiles.incarca("eveniment_rapid")
        p.segment_minute = 0.01  # 0,6 s: mai multe segmente
        cls.id2, cls.f2 = cls._inregistreaza(p, secunde=2.2, conditie="cald")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def _inregistreaza(cls, profil, secunde=1.2, conditie="rece"):
        rec = Recorder(profil, FakeSource(latenta_ms=5), dir_date=cls.dir, jurnal=Jurnal(), conditie=conditie)
        rec.porneste()
        time.sleep(secunde / 2)
        rec.marcaj("Cuplez ambreiajul")
        time.sleep(secunde / 2)
        rec.opreste()
        time.sleep(1.1)  # id-urile au rezolutie de o secunda
        return rec.folder.name, rec.folder

    def kw(self):
        return {"dir_date": self.dir}

    def test_lista_si_detaliu(self):
        ls = sesiuni.lista(**self.kw())
        self.assertEqual([s["id"] for s in ls], sorted([self.id1, self.id2], reverse=True))
        s = next(s for s in ls if s["id"] == self.id1)
        self.assertEqual(s["stare"], "finalizată")
        self.assertEqual(s["conditie"], "rece")
        self.assertGreater(s["randuri"], 5)
        det = sesiuni.incarca(self.id1, **self.kw())
        self.assertNotIn("profil_toml", det["sesiune"])
        self.assertTrue(any(e["tip"] == "marcaj" for e in det["evenimente"]))
        self.assertEqual({e["moment"] for e in det["erori"]}, {"start", "stop"})
        self.assertIn("STATUS_GEMISCH", det["instantaneu"]["joburi"])
        self.assertIn("rpm", det["rezumat"]["coloane"])
        self.assertIn("tmot_start", det["rezumat"])

    def test_mai_multe_segmente(self):
        self.assertGreater(len(list(self.f2.glob("date_*.csv"))), 1)
        s = json.loads((self.f2 / "sesiune.json").read_text(encoding="utf-8"))
        d = sesiuni.date(self.id2, ["rpm"], **self.kw())
        self.assertEqual(len(d["t"]), s["randuri"])
        self.assertEqual(d["t"], sorted(d["t"]))

    def test_celule_goale_sunt_null(self):
        d = sesiuni.date(self.id1, ["rpm", "lu1"], **self.kw())
        self.assertIsNotNone(d["lu1"][0])
        self.assertTrue(all(v is None for v in d["lu1"][1:]))
        self.assertTrue(all(v is not None for v in d["rpm"]))

    def test_interval_si_reducere(self):
        d = sesiuni.date(self.id1, ["rpm"], de_la=0.5, pana_la=0.8, **self.kw())
        self.assertTrue(all(0.5 <= t <= 0.8 for t in d["t"]))
        tot = sesiuni.date(self.id1, ["rpm"], **self.kw())
        red = sesiuni.date(self.id1, ["rpm"], max_puncte=6, **self.kw())
        self.assertLess(len(red["t"]), len(tot["t"]))
        self.assertEqual(max(v for v in red["rpm"]), max(tot["rpm"]))  # extremele se pastreaza
        self.assertEqual(min(v for v in red["rpm"]), min(tot["rpm"]))

    def test_coloane_text_si_reducere(self):
        d = sesiuni.date(self.id1, ["rpm", "marcaj", "steaguri", "t_iso"], **self.kw())
        self.assertEqual(len(d["marcaj"]), len(d["t"]))
        self.assertTrue(all(isinstance(x, str) for x in d["marcaj"] + d["steaguri"] + d["t_iso"]))
        red = sesiuni.date(self.id1, ["rpm", "marcaj"], max_puncte=6, **self.kw())  # nu cade pe siruri
        self.assertEqual(len(red["marcaj"]), len(red["t"]))

    def test_rand_cel_mai_apropiat(self):
        tot = sesiuni.date(self.id1, ["rpm"], **self.kw())
        r = sesiuni.rand(self.id1, tot["t"][3] + 0.0001, **self.kw())
        self.assertEqual(r["t_rel_s"], tot["t"][3])
        self.assertEqual(r["rpm"], tot["rpm"][3])

    def test_sesiune_json_lipsa_si_rand_trunchiat(self):
        nou = "2026-01-01_120000_proba_necunoscut"
        f = self.dir / "sesiuni" / nou
        f.mkdir()
        (f / "date_001.csv").write_bytes(
            b"t_iso,t_rel_s,ciclu,ciclu_ms,rpm,marcaj,steaguri\r\n"
            b"2026-01-01T12:00:00.100,0.1,1,10,800,,\r\n"
            b"2026-01-01T12:00:00.200,0.2,2,10,810,,\r\n"
            b"2026-01-01T12:00:00.3")
        s = next(s for s in sesiuni.lista(**self.kw()) if s["id"] == nou)
        self.assertEqual(s["stare"], "întreruptă")
        self.assertEqual(s["randuri"], 2)
        self.assertEqual(sesiuni.date(nou, ["rpm"], **self.kw())["rpm"], [800.0, 810.0])
        activ = next(s for s in sesiuni.lista(folder_activ=f, **self.kw()) if s["id"] == nou)
        self.assertEqual(activ["stare"], "în desfășurare")

    def test_sesiune_activa_cu_statistici_zero_in_json(self):
        """Pana la oprire sesiune.json are statistici zero: durata si cicluri/s se calculeaza din date."""
        nou = "2026-01-03_120000_activa_cald"
        f = self.dir / "sesiuni" / nou
        f.mkdir()
        (f / "sesiune.json").write_text(json.dumps({"profil": "activa", "conditie": "cald", "start": "2026-01-03T12:00:00",
                                                    "statistici": {"durata_s": 0.0, "cicluri_pe_s": 0.0}}),
                                        encoding="utf-8")
        (f / "date_001.csv").write_text("t_iso,t_rel_s,ciclu,ciclu_ms,rpm,marcaj,steaguri\n"
                                        "2026-01-03T12:00:00.0,0.0,1,10,800,,\n"
                                        "2026-01-03T12:00:02.0,2.0,2,10,810,,\n", encoding="utf-8")
        s = next(s for s in sesiuni.lista(folder_activ=f, **self.kw()) if s["id"] == nou)
        self.assertEqual(s["stare"], "în desfășurare")
        self.assertEqual(s["durata_s"], 2.0)
        self.assertEqual(s["cicluri_pe_s"], 1.0)

    def test_un_singur_rand(self):
        nou = "2026-01-02_120000_unu_necunoscut"
        f = self.dir / "sesiuni" / nou
        f.mkdir()
        (f / "date_001.csv").write_text("t_iso,t_rel_s,ciclu,ciclu_ms,rpm,marcaj,steaguri\n"
                                        "2026-01-02T12:00:00.1,0.1,1,10,800,,\n", encoding="utf-8")
        d = sesiuni.date(nou, ["rpm"], **self.kw())
        self.assertEqual(d["rpm"], [800.0])
        self.assertEqual(sesiuni.rezumat(nou, **self.kw())["durata_s"], 0)

    def test_id_ostile(self):
        for rau in ("..\\..", "x/../y", "a:b", "../sesiuni", "2026-11-02_135337_x/..", ""):
            with self.assertRaises(sesiuni.IdInvalid, msg=rau):
                sesiuni.incarca(rau, **self.kw())
        with self.assertRaises(sesiuni.NuExista):
            sesiuni.incarca("2020-01-01_000000_nu_exista", **self.kw())

    def test_lista_alba_de_fisiere(self):
        self.assertTrue(sesiuni.fisier(self.id1, "date_001.csv", **self.kw()).is_file())
        self.assertTrue(sesiuni.fisier(self.id1, "erori_start.json", **self.kw()).is_file())
        for rau in ("..\\sesiune.json", "../../x", "secret.txt", "date_1.csv", "erori_.json/../x"):
            with self.assertRaises(sesiuni.NuExista, msg=rau):
                sesiuni.fisier(self.id1, rau, **self.kw())

    def test_coloana_necunoscuta(self):
        with self.assertRaises(sesiuni.IdInvalid):
            sesiuni.date(self.id1, ["nu_exista"], **self.kw())

    def test_rezumat_pe_fragment(self):
        tot = sesiuni.rezumat(self.id1, **self.kw())
        d = sesiuni.date(self.id1, ["rpm"], **self.kw())
        t0, t1 = d["t"][0], d["t"][-1]
        mijloc = (t0 + t1) / 2
        fr = sesiuni.rezumat(self.id1, de_la=t0, pana_la=mijloc, **self.kw())
        asteptat = [i for i, t in enumerate(d["t"]) if t <= mijloc]
        self.assertEqual(fr["randuri"], len(asteptat))
        self.assertLess(fr["randuri"], tot["randuri"])
        vals = [d["rpm"][i] for i in asteptat if d["rpm"][i] is not None]
        self.assertAlmostEqual(fr["coloane"]["rpm"]["max"], max(vals))
        self.assertAlmostEqual(fr["coloane"]["rpm"]["medie"], sum(vals) / len(vals))
        self.assertEqual(fr["de_la"], d["t"][0])
        self.assertLessEqual(fr["pana_la"], mijloc)
        self.assertIn("steaguri", fr)
        self.assertNotIn("de_la", tot)  # fara fragment: acelasi format ca inainte
        # fragment fara randuri
        gol = sesiuni.rezumat(self.id1, de_la=t1 + 100, pana_la=t1 + 200, **self.kw())
        self.assertEqual((gol["randuri"], gol["durata_s"], gol["coloane"]), (0, 0, {}))
        # doar un capat
        self.assertEqual(sesiuni.rezumat(self.id1, de_la=t0, **self.kw())["randuri"], tot["randuri"])

    def test_fragmente_salvate(self):
        self.assertEqual(sesiuni.fragmente(self.id1, **self.kw()), [])
        l = sesiuni.adauga_fragment(self.id1, "  Cuplare 2 ", 3.5, 8, **self.kw())
        self.assertEqual([(x["id"], x["nume"], x["de_la"], x["pana_la"]) for x in l], [("f1", "Cuplare 2", 3.5, 8.0)])
        sesiuni.adauga_fragment(self.id1, "Început", 0, 2, **self.kw())
        l = sesiuni.fragmente(self.id1, **self.kw())
        self.assertEqual([x["nume"] for x in l], ["Început", "Cuplare 2"])  # ordonate dupa inceput
        # fisierul e in afara folderului sesiunii, care ramane neatins
        self.assertTrue((self.dir / "fragmente" / f"{self.id1}.json").is_file())
        self.assertFalse(any("fragment" in p.name for p in self.f1.iterdir()))
        self.assertEqual(sesiuni.fragmente(self.id2, **self.kw()), [])  # pe sesiune
        # id nou dupa stergere nu il reutilizeaza pe unul existent
        sesiuni.sterge_fragment(self.id1, "f1", **self.kw())
        l = sesiuni.adauga_fragment(self.id1, "Altul", 5, 6, **self.kw())
        self.assertEqual(sorted(x["id"] for x in l), ["f2", "f3"])
        with self.assertRaises(sesiuni.NuExista):
            sesiuni.sterge_fragment(self.id1, "f1", **self.kw())
        for x in list(l):
            sesiuni.sterge_fragment(self.id1, x["id"], **self.kw())
        self.assertEqual(sesiuni.fragmente(self.id1, **self.kw()), [])

    def test_fragmente_date_invalide(self):
        for nume, de, pana in [("", 1, 2), ("   ", 1, 2), ("x" * 61, 1, 2), (None, 1, 2), ("a", 2, 2), ("a", 3, 2),
                               ("a", -1, 2), ("a", "1", 2), ("a", True, 2), ("a", float("nan"), 2),
                               ("a", 1, float("inf"))]:
            with self.assertRaises(sesiuni.IdInvalid, msg=repr((nume, de, pana))):
                sesiuni.adauga_fragment(self.id1, nume, de, pana, **self.kw())
        with self.assertRaises(sesiuni.IdInvalid):
            sesiuni.fragmente("../x", **self.kw())
        with self.assertRaises(sesiuni.NuExista):
            sesiuni.fragmente("2020-01-01_000000_inexistent", **self.kw())
        self.assertEqual(sesiuni.fragmente(self.id1, **self.kw()), [])

    def test_fragmente_fisier_stricat(self):
        c = self.dir / "fragmente"
        c.mkdir(exist_ok=True)
        (c / f"{self.id2}.json").write_text("nu e json", encoding="utf-8")
        self.assertEqual(sesiuni.fragmente(self.id2, **self.kw()), [])
        (c / f"{self.id2}.json").write_text(json.dumps({"fragmente": [{"id": "f1"}, 5, {"id": "f2", "nume": "ok", "de_la": 1, "pana_la": 2}]}),
                                            encoding="utf-8")
        self.assertEqual([x["id"] for x in sesiuni.fragmente(self.id2, **self.kw())], ["f2"])
        (c / f"{self.id2}.json").unlink()


class TestSesiuniReale(unittest.TestCase):
    """Test de fum pe datele reale din bmw-data; sarit daca folderul lipseste."""

    def setUp(self):
        if not (DIR_DATE / "sesiuni").is_dir():
            self.skipTest("bmw-data\\sesiuni lipsește")

    def test_toate_se_incarca(self):
        ls = sesiuni.lista()
        for s in ls:
            det = sesiuni.incarca(s["id"])
            self.assertIn(det["stare"], ("finalizată", "întreruptă", "în desfășurare"))

    def test_sesiunea_mare(self):
        id_ = "2026-11-02_135337_drum_lung_oras_rece"
        if not (DIR_DATE / "sesiuni" / id_).is_dir():
            self.skipTest("sesiunea de referință lipsește")
        cols = ["rpm", "rpm_tinta", "tmot", "sarcina", "pedala", "cuplu"]
        sesiuni.date(id_, cols)  # prima citire
        t0 = time.perf_counter()
        d = sesiuni.date(id_, cols)
        ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(d["t"]), 13456)
        # tot setul (~600 KB, JSON compact) nu incape in 500 KB; cu reducere min/max da
        self.assertLess(len(json.dumps(d, separators=(",", ":"))), 700_000)
        red = sesiuni.date(id_, cols, max_puncte=5000)
        self.assertLess(len(json.dumps(red, separators=(",", ":"))), 500_000)
        self.assertLess(ms, 200)


if __name__ == "__main__":
    unittest.main()
