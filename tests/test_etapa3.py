"""Etapa 3 cap-coada cu FakeSource: profile, steaguri, erori, conexiune."""
import csv
import json
import tempfile
import time
import unittest
from pathlib import Path

from bmwdiag import profiles
from bmwdiag.jurnal import Jurnal
from bmwdiag.recorder import Recorder
from bmwdiag.sources import FakeSource


def citeste_csv(cale):
    with open(cale, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def evenimente(folder, tip=None):
    ev = citeste_csv(folder / "evenimente.csv")
    return [e for e in ev if tip is None or e["tip"] == tip]


class Baza(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def recorder(self, sursa, profil="eveniment_rapid", **kw):
        p = profiles.incarca(profil) if isinstance(profil, str) else profil
        return Recorder(p, sursa, dir_date=self.dir, jurnal=Jurnal(), **kw)


class TestProfileLivrate(unittest.TestCase):
    def test_cele_patru_profile(self):
        self.assertEqual(set(profiles.lista()) >= {"eveniment_rapid", "drum_lung_oras", "ralanti_incalzire",
                                                   "instantaneu_complet"}, True)
        for nume in ("eveniment_rapid", "drum_lung_oras", "ralanti_incalzire", "instantaneu_complet"):
            with self.subTest(profil=nume):
                p = profiles.incarca(nume)
                self.assertEqual(p.ecu, "MEV9N46L")
                self.assertNotIn("AIF_LESEN", p.toate_joburile())

    def test_detalii(self):
        d = profiles.incarca("drum_lung_oras")
        self.assertEqual((d.segment_minute, d.erori_interval_minute), (10, 10))
        self.assertIn("sonda_post_b2", d.aliasuri())
        r = profiles.incarca("ralanti_incalzire")
        prag = next(s for s in r.steaguri if s["nume"] == "tmot_prag")
        self.assertEqual(prag["praguri"], [40, 60, 70, 80, 90])
        self.assertEqual({g.nume: g.la_fiecare_s for g in r.grupuri}, {"rapid": 0, "la_10s": 10, "la_60s": 60})
        self.assertEqual(profiles.incarca("instantaneu_complet").cicluri_max, 1)


class TestCadereLaCuplare(Baza):
    """Criteriul etapei 3: steagul apare la cald si NU la rece."""

    def cuplari(self, tmot_start):
        sursa = FakeSource(latenta_ms=5, perioada_cuplare_s=0, tmot_start=tmot_start, seed=3)
        p = profiles.incarca("eveniment_rapid")
        p.instantaneu_la_start, p.erori_la_start, p.erori_la_stop = [], False, False
        rec = self.recorder(sursa, p)
        rec.porneste()
        time.sleep(0.5)
        for _ in range(3):           # trei cuplari, la 3 s una de alta
            sursa.cupleaza()
            time.sleep(3.0)
        rec.opreste()
        return rec

    def test_cald_da_rece_nu(self):
        cald = self.cuplari(90)
        rece = self.cuplari(20)
        self.assertEqual(cald.numar_steaguri["cadere_la_cuplare"], 3)
        self.assertEqual(rece.numar_steaguri["cadere_la_cuplare"], 0)

        randuri = citeste_csv(cald.folder / "date_001.csv")
        cu_steag = [r for r in randuri if "cadere_la_cuplare" in r["steaguri"]]
        self.assertEqual(len(cu_steag), 3)
        self.assertTrue(all(float(r["rpm"]) < 600 for r in cu_steag))    # 700 la ralanti, cade ~270
        ev = evenimente(cald.folder, "steag")
        self.assertEqual(sum("cadere_la_cuplare" in e["detalii"] for e in ev), 3)
        self.assertIn("Steag cadere_la_cuplare", (cald.folder / "jurnal.txt").read_text(encoding="utf-8"))
        ses = json.loads((cald.folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["statistici"]["steaguri"]["cadere_la_cuplare"], 3)


class TestErori(Baza):
    def test_eroare_noua_la_stop(self):
        sursa = FakeSource(latenta_ms=5)
        rec = self.recorder(sursa)
        rec.porneste()
        time.sleep(0.6)
        sursa.adauga_eroare(11427, "CDKHSVSA2 (simulat)")
        rec.opreste()
        self.assertEqual(rec.numar_steaguri["eroare_noua"], 1)
        self.assertTrue((rec.folder / "erori_stop.json").is_file())
        self.assertIn("eroare nouă 2CA3", (rec.folder / "jurnal.txt").read_text(encoding="utf-8"))

    def test_la_cerere_si_schimbare_stare(self):
        sursa = FakeSource(latenta_ms=5)
        rec = self.recorder(sursa)
        rec.porneste()
        time.sleep(0.5)
        sursa.adauga_eroare(11107, "CDKPH2 (simulat)", 1, "Fehler momentan vorhanden")
        rec.cere_erori()
        time.sleep(0.5)
        rec.opreste()
        self.assertEqual(len(list(rec.folder.glob("erori_cerere_*.json"))), 1)
        self.assertEqual(rec.numar_steaguri["eroare_noua"], 1)   # o data la cerere, nu din nou la stop
        jurnal = (rec.folder / "jurnal.txt").read_text(encoding="utf-8")
        self.assertIn("și-a schimbat starea", jurnal)

    def test_interval(self):
        p = profiles.incarca("eveniment_rapid")
        p.erori_interval_minute = 0.01  # 0,6 s
        p.instantaneu_la_start = []
        rec = self.recorder(FakeSource(latenta_ms=5), p)
        rec.porneste()
        time.sleep(1.5)
        rec.opreste()
        intermediare = [f for f in rec.folder.glob("erori_*.json") if f.stem not in ("erori_start", "erori_stop")]
        self.assertGreaterEqual(len(intermediare), 1)
        self.assertEqual(rec.numar_steaguri["eroare_noua"], 0)

    def test_detaliu_pentru_fiecare_eroare(self):
        rec = self.recorder(FakeSource(latenta_ms=5), "instantaneu_complet")
        rec.ruleaza()
        e = json.loads((rec.folder / "erori_start.json").read_text(encoding="utf-8"))
        self.assertEqual(e["fs_lesen"]["seturi"][0]["F_HEX_CODE"], "hex:2b6388")
        detaliu = e["detalii"]["11107"]
        self.assertEqual(detaliu["seturi"][0]["F_PCODE_STRING"], "P0365")
        self.assertEqual(detaliu["seturi"][-1]["JOB_MESSAGE"], "Fehlerspeicher gelesen")


class TestInstantaneuComplet(Baza):
    def test_o_singura_trecere(self):
        rec = self.recorder(FakeSource(latenta_ms=5), "instantaneu_complet")
        rec.ruleaza()   # se opreste singur
        ses = json.loads((rec.folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["randuri"], 1)
        self.assertIn("1 cicluri", ses["motiv_oprire"])
        inst = json.loads((rec.folder / "instantaneu_start.json").read_text(encoding="utf-8"))["joburi"]
        self.assertEqual(len(inst), 28)
        nereusite = [j for j, r in inst.items() if not r["ok"]]
        self.assertEqual(nereusite, [])
        self.assertFalse((rec.folder / "erori_stop.json").exists())


class TestUnitati(Baza):
    def test_prima_citire_fara_filtru(self):
        apeluri = []
        sursa = FakeSource(latenta_ms=5)
        run = sursa.run
        sursa.run = lambda job, filtru="", parametri="", ecu=None: apeluri.append((job, filtru)) or \
            run(job, filtru, parametri, ecu)
        rec = self.recorder(sursa)
        rec.porneste()
        time.sleep(0.6)
        rec.opreste()
        mess = [f for j, f in apeluri if j == "STATUS_MESSWERTE"]
        self.assertEqual(mess[0], "")                      # prima: fara filtru
        self.assertTrue(all(f.startswith("STAT_NMOT_WERT;") for f in mess[1:]))
        self.assertNotIn("EINH", ";".join(mess[1:]))
        col = json.loads((rec.folder / "coloane.json").read_text(encoding="utf-8"))
        self.assertEqual(col["tmot"]["unitate"], "Grad C")
        randuri = citeste_csv(rec.folder / "date_001.csv")
        self.assertTrue(randuri[0]["rpm"])                 # valorile vin si din citirea nefiltrata


class TestConexiune(Baza):
    def test_pierduta_si_restabilita(self):
        sursa = FakeSource(latenta_ms=5)
        p = profiles.incarca("eveniment_rapid")
        p.instantaneu_la_start, p.erori_la_start, p.erori_la_stop = [], False, False
        rec = self.recorder(sursa, p)
        resetari = []
        reset = sursa.reset
        sursa.reset = lambda: resetari.append(1) or reset()
        rec.porneste()
        time.sleep(0.5)
        sursa.deconectat = True       # cablul scos
        time.sleep(2.5)               # 3 cicluri x 0,5 s -> pierduta, apoi reset dupa 1 s
        stare_in_pana = rec.stare()["stare"]
        sursa.deconectat = False      # cablul pus la loc
        time.sleep(3.0)               # urmatorul reset (dupa 2 s) si prima citire reusita
        rec.opreste()
        self.assertEqual(stare_in_pana, "reconectare")
        self.assertEqual(rec.numar_steaguri["conexiune_pierduta"], 1)
        self.assertEqual(rec.numar_steaguri["conexiune_restabilita"], 1)
        self.assertGreaterEqual(len(resetari), 1)
        ses = json.loads((rec.folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["motiv_oprire"], "oprit de utilizator")   # sesiunea nu s-a oprit
        randuri = citeste_csv(rec.folder / "date_001.csv")
        self.assertTrue(randuri[-1]["rpm"])
        tipuri = [e["detalii"].split(":")[0] for e in evenimente(rec.folder, "steag")]
        self.assertEqual(tipuri, ["conexiune_pierduta", "conexiune_restabilita"])


class TestProfilRespins(Baza):
    def test_job_refuzat_mesaj_clar(self):
        text = (profiles.DIR_PROFILE / "eveniment_rapid.toml").read_text(encoding="utf-8")
        cale = self.dir / "rau.toml"
        cale.write_text(text.replace('job = "STATUS_FASTA2"', 'job = "FS_LOESCHEN"'), encoding="utf-8")
        with self.assertRaises(profiles.ProfilInvalid) as cm:
            profiles.incarca(cale)
        mesaj = str(cm.exception)
        self.assertIn("nu se poate încărca", mesaj)
        self.assertIn("FS_LOESCHEN", mesaj)
        self.assertIn("doar citire", mesaj)


if __name__ == "__main__":
    unittest.main()
