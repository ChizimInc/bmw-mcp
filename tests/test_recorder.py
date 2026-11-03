import csv
import json
import tempfile
import time
import unittest
from pathlib import Path

from bmwdiag import profiles
from bmwdiag.jurnal import Jurnal
from bmwdiag.recorder import Recorder
from bmwdiag.sources import FakeSource, ReplaySource


def citeste_csv(cale):
    with open(cale, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profil = profiles.incarca("eveniment_rapid")

    def tearDown(self):
        self.tmp.cleanup()

    def inregistreaza(self, sursa, secunde=1.5, profil=None, **kw):
        rec = Recorder(profil or self.profil, sursa, dir_date=self.dir, jurnal=Jurnal(), **kw)
        rec.porneste()
        time.sleep(secunde)
        rec.marcaj("Cuplez ambreiajul")
        time.sleep(0.3)
        rec.opreste()
        return rec

    def test_folder_sesiune_complet(self):
        rec = self.inregistreaza(FakeSource(latenta_ms=5), conditie="rece", nota="test")
        f = rec.folder
        self.assertTrue(f.name.endswith("_eveniment_rapid_rece"))
        for nume in ("sesiune.json", "date_001.csv", "coloane.json", "evenimente.csv", "erori_start.json",
                     "erori_stop.json", "instantaneu_start.json", "jurnal.txt"):
            self.assertTrue((f / nume).is_file(), nume)

        ses = json.loads((f / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["conditie"], "rece")
        self.assertEqual(ses["nota"], "test")
        self.assertIn("[[grup]]", ses["profil_toml"])
        self.assertEqual(ses["motiv_oprire"], "oprit de utilizator")
        self.assertGreater(ses["statistici"]["cicluri_pe_s"], 1)
        self.assertIn("STATUS_MESSWERTE", ses["statistici"]["joburi"])

        randuri = citeste_csv(f / "date_001.csv")
        self.assertEqual(len(randuri), ses["randuri"])
        self.assertEqual(list(randuri[0])[:4], ["t_iso", "t_rel_s", "ciclu", "ciclu_ms"])
        self.assertEqual(list(randuri[0])[-2:], ["marcaj", "steaguri"])
        self.assertTrue(all(r["rpm"] and r["sarcina"] for r in randuri))
        # grupul lent (la 5 s) e citit doar in primul ciclu; in rest celule goale
        self.assertTrue(randuri[0]["lu1"])
        self.assertTrue(all(r["lu1"] == "" for r in randuri[1:]))
        self.assertEqual(sum(1 for r in randuri if r["marcaj"] == "Cuplez ambreiajul"), 1)
        t = [float(r["t_rel_s"]) for r in randuri]
        self.assertEqual(t, sorted(t))

        col = json.loads((f / "coloane.json").read_text(encoding="utf-8"))
        self.assertEqual(col["rpm"], {"job": "STATUS_MESSWERTE", "rezultat": "STAT_NMOT_WERT", "unitate": "1/min"})
        self.assertEqual(col["sarcina"]["unitate"], "%")

        ev = citeste_csv(f / "evenimente.csv")
        self.assertIn("marcaj", {e["tip"] for e in ev})
        err = json.loads((f / "erori_start.json").read_text(encoding="utf-8"))
        self.assertEqual(err["fs_lesen"]["seturi"][0]["F_ORT_NR"], 11107)
        self.assertIn("11107", err["detalii"])
        jurnal = (f / "jurnal.txt").read_text(encoding="utf-8")
        self.assertIn("Erori (start): 1: 2B63", jurnal)

    def test_erori_job_traduse_si_rarite(self):
        sursa = FakeSource(latenta_ms=5)
        rec = Recorder(self.profil, sursa, dir_date=self.dir, jurnal=Jurnal())
        rec.porneste()
        time.sleep(0.5)
        sursa.deconectat = True
        time.sleep(1.5)
        rec.opreste()
        jurnal = (rec.folder / "jurnal.txt").read_text(encoding="utf-8")
        self.assertIn("cablul nu e în laptop", jurnal)
        # o singura linie pe job in fereastra de 10 s, desi bucla a esuat de mai multe ori
        self.assertEqual(jurnal.count("STATUS_MESSWERTE: Portul COM"), 1)
        self.assertGreater(rec.erori, 2)
        randuri = citeste_csv(rec.folder / "date_001.csv")
        self.assertEqual(randuri[-1]["rpm"], "")  # celule goale la job esuat

    def test_durata_max(self):
        self.profil.durata_max_minute = 0.01  # 0,6 s
        rec = Recorder(self.profil, FakeSource(latenta_ms=5), dir_date=self.dir, jurnal=Jurnal())
        rec.ruleaza()  # sincron: trebuie sa se opreasca singur
        ses = json.loads((rec.folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["motiv_oprire"], "durata maximă atinsă")

    def test_segmente(self):
        self.profil.segment_minute = 0.01
        rec = self.inregistreaza(FakeSource(latenta_ms=5), secunde=1.5)
        segmente = sorted(rec.folder.glob("date_*.csv"))
        self.assertGreaterEqual(len(segmente), 2)
        total = sum(len(citeste_csv(s)) for s in segmente)
        ses = json.loads((rec.folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(total, ses["randuri"])

    def test_replay_al_unei_sesiuni(self):
        rec = self.inregistreaza(FakeSource(latenta_ms=5), secunde=1.0)
        original = citeste_csv(rec.folder / "date_001.csv")
        self.profil.instantaneu_la_start = []
        self.profil.erori_la_start = self.profil.erori_la_stop = False
        rec2 = Recorder(self.profil, ReplaySource(rec.folder), dir_date=self.dir, jurnal=Jurnal())
        rec2.ruleaza()
        copie = citeste_csv(rec2.folder / "date_001.csv")
        self.assertEqual(len(copie), len(original))
        self.assertEqual([r["rpm"] for r in copie], [r["rpm"] for r in original])
        ses = json.loads((rec2.folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertIn("sfârșitul", ses["motiv_oprire"])

    def test_stare(self):
        rec = Recorder(self.profil, FakeSource(latenta_ms=5), dir_date=self.dir, jurnal=Jurnal())
        rec.porneste()
        time.sleep(0.8)
        s = rec.stare()
        rec.opreste()
        self.assertEqual(s["stare"], "inregistreaza")
        self.assertGreater(s["cicluri_pe_s"], 1)
        self.assertLess(s["ultima_reusita_s"], 2)
        self.assertIsNotNone(s["valori"]["rpm"]["valoare"])
        self.assertEqual(rec.stare()["stare"], "oprit")


if __name__ == "__main__":
    unittest.main()
