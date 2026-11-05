"""Modul live al recorderului: aceeasi bucla de citire, dar fara nicio scriere pe disc."""
import collections
import json
import re
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


class TestToateSenzorii(unittest.TestCase):
    """Profilul toate_senzorii: doar live; joburile STATUS_* se descopera din SGBD si devin coloane."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def live(self, sursa=None, secunde=2.5):
        rec = Recorder(profiles.incarca("toate_senzorii"), sursa or FakeSource(latenta_ms=2), dir_date=self.dir,
                       jurnal=Jurnal(), scrie=False)
        rec.porneste()
        time.sleep(secunde)
        return rec

    def test_profilul_se_incarca_si_nu_merge_la_inregistrare(self):
        p = profiles.incarca("toate_senzorii")
        self.assertTrue(p.toate_senzorii)
        self.assertEqual([(g.nume, g.rotativ) for g in p.grupuri], [("rapid", False), ("lent", True)])
        self.assertFalse(profiles.incarca("eveniment_rapid").toate_senzorii)
        with self.assertRaises(ValueError):
            Recorder(p, FakeSource(), dir_date=self.dir, jurnal=Jurnal())  # scrie=True

    def test_descopera_joburile_si_creeaza_coloane(self):
        rec = self.live()
        rec.opreste()
        al = list(rec.mapare)
        self.assertEqual(list(rec.mapare)[:3], ["rpm", "rpm_tinta", "tmot"])  # aliasurile din profil raman primele
        self.assertIn("messwerte__tka_wert", al)           # rezultat din MESSWERTE care nu avea alias in profil
        self.assertIn("fasta3__fasta3_1_wert", al)          # job descoperit
        self.assertIn("digital__digital_1_ein", al)
        self.assertIn("oelsensor__oelsensor_text", al)      # rezultat text
        self.assertEqual(rec.mapare["fasta3__fasta3_1_wert"]["job"], "STATUS_FASTA3")
        self.assertEqual(rec.mapare["fasta3__fasta3_1_wert"]["rezultat"], "STAT_FASTA3_1_WERT")
        self.assertTrue(rec.mapare["messwerte__tka_wert"]["unitate"])
        self.assertTrue(all(re.fullmatch(r"[a-z][a-z0-9_]*", a) for a in al), al)
        self.assertEqual(len(al), len(set(al)))
        self.assertGreater(len(al), 100)
        # nu se citesc joburi cu argumente, joburi nepermise sau care nu sunt STATUS_*
        joburi = {m["job"] for m in rec.mapare.values()}
        for nepermis in ("STATUS_ADD", "FS_LESEN", "IDENT", "STEUERN_PROBA", "STATUS_X_LOESCHEN"):
            self.assertNotIn(nepermis, joburi)
        self.assertEqual(list(self.dir.rglob("*")), [])    # nimic scris pe disc

    def test_job_care_raspunde_cu_eroare_ecu_e_dezactivat(self):
        rec = self.live()
        rec.opreste()
        self.assertIn("STATUS_KVA", rec._dezactivate)
        self.assertNotIn("STATUS_MESSWERTE", rec._dezactivate)
        self.assertTrue(any("dezactivat" in t for _, t in rec.jurnal.de_la(0)))

    def test_jobul_rapid_in_fiecare_ciclu_celelalte_pe_rand(self):
        rec = self.live(secunde=3.0)
        rec.opreste()
        rand = list(rec.buffer)
        self.assertGreater(len(rand), 40)
        cu_rpm = sum(1 for r in rand if "rpm" in r)
        self.assertGreaterEqual(cu_rpm / len(rand), 0.95)   # grupul rapid nu e incetinit
        cu_digital = sum(1 for r in rand if "digital__digital_1_ein" in r)
        self.assertGreater(cu_digital, 0)
        self.assertLess(cu_digital, len(rand) * 0.3)         # un job pe ciclu din ~40, nu in fiecare ciclu
        # pe ciclu: MESSWERTE + FASTA2 (grupul rapid) si cel mult un job din fiecare grup rotativ ("lent" si cel descoperit)
        for r in rand:
            joburi = {rec.mapare[a]["job"] for a in r if a in rec.mapare}
            self.assertLessEqual(len(joburi - {"STATUS_MESSWERTE", "STATUS_FASTA2"}), 2)

    def test_date_live_trimite_maparea_doar_cand_s_a_schimbat(self):
        rec = self.live()
        d = rec.date_live(0, None, 0, -1)
        rec.opreste()
        self.assertIn("mapare", d)
        self.assertEqual(set(d["mapare"]), set(d["aliasuri"]))
        self.assertEqual(set(d["aliasuri"]), set(rec.mapare))
        d2 = rec.date_live(d["ciclu_ultim"], None, d["ev_ultim"], d["v_mapare"])
        self.assertNotIn("mapare", d2)
        self.assertNotIn("aliasuri", d2)
        self.assertIsInstance(d["valori"]["oelsensor__oelsensor_text"], str)    # text, in valori
        self.assertTrue(all(v is None for v in d["oelsensor__oelsensor_text"]))  # dar nu numar in coloane
        self.assertTrue(any(v is not None for v in d["fasta3__fasta3_1_wert"]))
        self.assertEqual(len(d["fasta3__fasta3_1_wert"]), len(d["t"]))

    def test_fara_lista_de_joburi_se_folosesc_cele_cunoscute(self):
        class FaraJobs(FakeSource):
            def _seturi_descriere(self, job, parametri):
                return [{"JOB_STATUS": "OKAY"}] if job == "_JOBS" else super()._seturi_descriere(job, parametri)

        rec = self.live(FaraJobs(latenta_ms=2))
        rec.opreste()
        joburi = {m["job"] for m in rec.mapare.values()}
        self.assertIn("STATUS_GEMISCH", joburi)
        self.assertNotIn("STATUS_FASTA3", joburi)           # nu e in lista de rezerva
        self.assertTrue(any("joburile STATUS_* cunoscute" in t for _, t in rec.jurnal.de_la(0)))

    def test_exporta_cu_coloanele_descoperite(self):
        rec = self.live()
        rec.opreste()
        folder = rec.exporta_buffer(60, self.dir, "cald", "toti senzorii")
        det = sesiuni.incarca(folder.name, dir_date=self.dir)
        self.assertIn("rpm", det["rezumat"]["coloane"])
        self.assertIn("fasta3__fasta3_1_wert", det["rezumat"]["coloane"])
        self.assertIn("digital__digital_1_ein", det["coloane"])
        d = sesiuni.date(folder.name, ["messwerte__tka_wert"], dir_date=self.dir)
        self.assertTrue(any(v is not None for v in d["messwerte__tka_wert"]))


if __name__ == "__main__":
    unittest.main()
