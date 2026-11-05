"""Modul live al recorderului: aceeasi bucla de citire, dar fara nicio scriere pe disc."""
import collections
import json
import tempfile
import time
import unittest
from pathlib import Path

from bmwdiag import profiles, sesiuni
from bmwdiag.jurnal import Jurnal
from bmwdiag.recorder import Recorder
from bmwdiag.sources import FakeSource


class TestLive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def recorder(self, **kw):
        return Recorder(profiles.incarca("eveniment_rapid"), FakeSource(latenta_ms=5), dir_date=self.dir,
                        jurnal=Jurnal(), scrie=False, **kw)

    def test_nu_scrie_nimic_pe_disc(self):
        rec = self.recorder()
        rec.porneste()
        time.sleep(1.0)
        rec.marcaj("proba")
        time.sleep(0.4)
        rec.opreste()
        self.assertEqual(list(self.dir.rglob("*")), [])
        self.assertIsNone(rec.folder)
        self.assertGreater(len(rec.buffer), 5)
        self.assertEqual(rec.stare()["stare"], "oprit")
        self.assertEqual(rec.stare()["mod"], "live")

    def test_cursor_fara_goluri_sau_dubluri(self):
        rec = self.recorder()
        rec.porneste()
        ciclu, vazute = 0, []
        for _ in range(4):
            time.sleep(0.35)
            d = rec.date_live(ciclu, ["rpm", "tmot"])
            vazute += d["ciclu"]
            self.assertEqual(len(d["t"]), len(d["rpm"]))
            self.assertFalse(d["reset"])
            ciclu = d["ciclu_ultim"]
        rec.opreste()
        self.assertGreater(len(vazute), 8)
        self.assertEqual(vazute, list(range(1, len(vazute) + 1)))
        self.assertEqual(sorted(set(vazute)), vazute)

    def test_reset_cand_cursorul_a_iesit_din_buffer(self):
        rec = self.recorder()
        rec.buffer = collections.deque(maxlen=5)
        rec.porneste()
        time.sleep(1.0)
        rec.opreste()
        d = rec.date_live(1)
        self.assertTrue(d["reset"])
        self.assertLessEqual(len(d["t"]), 5)
        self.assertFalse(rec.date_live(0)["reset"])  # de la inceput nu e reset

    def test_valorile_sunt_numere_sau_null(self):
        rec = self.recorder()
        rec.porneste()
        time.sleep(0.6)
        rec.opreste()
        d = rec.date_live(0)
        for v in d["rpm"]:
            self.assertTrue(v is None or isinstance(v, (int, float)))
        self.assertTrue(any(v is not None for v in d["rpm"]))
        with self.assertRaises(ValueError):
            rec.date_live(0, ["nu_exista"])

    def test_se_opreste_singur_fara_cereri(self):
        rec = self.recorder(inactiv_s=0.6)
        rec.porneste()
        time.sleep(0.3)
        rec.date_live(0)  # reinnoieste temporizatorul
        time.sleep(0.5)
        self.assertTrue(rec.activ)
        time.sleep(1.2)
        self.assertFalse(rec.activ)
        self.assertIn("inactivitate", rec.stare()["motiv_oprire"])
        self.assertFalse(rec.sursa.pornit)  # portul e eliberat

    def test_marcaj_in_evenimente_si_fara_limite_de_inregistrare(self):
        profil = profiles.incarca("eveniment_rapid")
        profil.cicluri_max = 3  # ar opri o inregistrare; live il ignora
        rec = Recorder(profil, FakeSource(latenta_ms=5), dir_date=self.dir, jurnal=Jurnal(), scrie=False)
        rec.porneste()
        time.sleep(0.3)
        rec.marcaj("Cuplez ambreiajul")
        time.sleep(0.6)
        d = rec.date_live(0)
        rec.opreste()
        self.assertGreater(d["ciclu_ultim"], 3)
        self.assertTrue(any(e["tip"] == "marcaj" and e["detalii"] == "Cuplez ambreiajul" for e in d["evenimente"]))
        self.assertEqual(rec.date_live(0, de_la_ev=d["ev_ultim"])["evenimente"], [])

    def test_exporta_buffer_ca_sesiune(self):
        rec = self.recorder()
        rec.porneste()
        time.sleep(0.5)
        rec.marcaj("in fereastra")
        time.sleep(0.8)
        rec.opreste()
        folder = rec.exporta_buffer(60, self.dir, "cald", "din live")
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["coloane.json", "date_001.csv", "evenimente.csv", "sesiune.json"])
        j = json.loads((folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual((j["origine"], j["conditie"], j["nota"]), ("live", "cald", "din live"))
        self.assertEqual(j["randuri"], len(rec.buffer))
        det = sesiuni.incarca(folder.name, dir_date=self.dir)  # se citeste ca orice sesiune
        self.assertEqual(det["stare"], "finalizată")
        self.assertEqual(det["rezumat"]["randuri"], len(rec.buffer))
        self.assertTrue(any(e["tip"] == "marcaj" for e in det["evenimente"]))
        d = sesiuni.date(folder.name, ["rpm"], dir_date=self.dir)
        self.assertEqual(d["t"][0], 0.0)
        # o fereastra mai scurta
        f2 = rec.exporta_buffer(0.3, self.dir, "rece")
        self.assertLess(sesiuni.incarca(f2.name, dir_date=self.dir)["rezumat"]["randuri"], len(rec.buffer))
        for arg in ({"secunde": 0}, {"secunde": -1}, {"secunde": True}, {"secunde": 5, "conditie": "x"}):
            with self.assertRaises(ValueError):
                rec.exporta_buffer(dir_date=self.dir, **{"secunde": 5, **arg})

    def test_export_doar_din_live_si_buffer_gol(self):
        gol = self.recorder()
        with self.assertRaises(ValueError):
            gol.exporta_buffer(10, self.dir)
        rec = Recorder(profiles.incarca("eveniment_rapid"), FakeSource(latenta_ms=5), dir_date=self.dir, jurnal=Jurnal())
        with self.assertRaises(ValueError):
            rec.exporta_buffer(10, self.dir)


if __name__ == "__main__":
    unittest.main()
