import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from bmwdiag import profiles, rezumat, sesiuni
from bmwdiag.jurnal import Jurnal
from bmwdiag.recorder import DIR_DATE, Recorder
from bmwdiag.sources import FakeSource


def ruleaza(*argv):
    """(cod, stdout, stderr)"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        cod = rezumat.main(list(argv))
    return cod, out.getvalue(), err.getvalue()


class TestRezumat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        rec = Recorder(profiles.incarca("eveniment_rapid"), FakeSource(latenta_ms=5), dir_date=cls.dir,
                       jurnal=Jurnal(), conditie="rece")
        rec.porneste()
        time.sleep(0.6)
        rec.marcaj("Cuplez ambreiajul")
        time.sleep(0.6)
        rec.opreste()
        cls.id, cls.folder = rec.folder.name, rec.folder
        cls.antes = cls._instantaneu(cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def _instantaneu(baza: Path):
        return {str(p.relative_to(baza)): (p.stat().st_mtime_ns, p.stat().st_size) for p in baza.rglob("*")}

    def test_text_dupa_id(self):
        cod, out, err = ruleaza(self.id, "--date", str(self.dir))
        self.assertEqual((cod, err), (0, ""))
        for cuvant in ("finalizată", "rece", "Rânduri", "Cicluri/s", "Turație", "rpm", "Min / medie / max",
                       "Steaguri pe tip", "Cuplez ambreiajul", "înainte", "Erori noi"):
            self.assertIn(cuvant, out)

    def test_dupa_calea_folderului(self):
        cod, out, _ = ruleaza(str(self.folder))
        self.assertEqual(cod, 0)
        self.assertIn(self.id, out)

    def test_coloane_si_filtru_evenimente(self):
        cod, out, _ = ruleaza(self.id, "--date", str(self.dir), "--coloane", "rpm,tmot", "--evenimente", "marcaj")
        self.assertEqual(cod, 0)
        self.assertIn("Turație", out)
        self.assertNotIn("Tensiunea bateriei", out)
        cod, out, _ = ruleaza(self.id, "--date", str(self.dir), "--evenimente", "eroare")
        self.assertEqual(cod, 0)
        self.assertNotIn("Cuplez ambreiajul", out)

    def test_coloana_necunoscuta(self):
        cod, _, err = ruleaza(self.id, "--date", str(self.dir), "--coloane", "nu_exista")
        self.assertNotEqual(cod, 0)
        self.assertIn("nu_exista", err)

    def test_json_valid(self):
        cod, out, err = ruleaza(self.id, "--date", str(self.dir), "--json")
        self.assertEqual((cod, err), (0, ""))
        j = json.loads(out)
        self.assertEqual(j["id"], self.id)
        self.assertEqual(j["stare"], "finalizată")
        self.assertIn("rpm", j["coloane"])
        self.assertEqual(j["coloane"]["rpm"]["eticheta"], "Turație")
        marcaje = [e for e in j["evenimente"] if e["tip"] == "marcaj"]
        self.assertEqual(len(marcaje), 1)
        self.assertEqual(set(marcaje[0]["fereastra"]), {"rpm", "sarcina", "pedala", "clapeta", "tmot"})
        self.assertEqual(set(marcaje[0]["fereastra"]["rpm"]), {"inainte", "min", "t_min", "dupa", "cadere"})

    def test_id_inexistent_si_ostil(self):
        for rau in ("2020-01-01_000000_nu_exista", "..\\..", "x/../y", "a:b", "../sesiuni", ""):
            cod, out, err = ruleaza(rau, "--date", str(self.dir))
            self.assertNotEqual(cod, 0, rau)
            self.assertEqual(out, "", rau)
            self.assertTrue(err.startswith("Eroare:"), rau)

    def test_folder_care_nu_e_sesiune(self):
        cod, _, err = ruleaza(str(self.dir))
        self.assertNotEqual(cod, 0)
        self.assertIn("Eroare", err)

    def test_un_singur_rand(self):
        f = self.dir / "sesiuni" / "2026-01-02_120000_unu_necunoscut"
        f.mkdir()
        (f / "date_001.csv").write_text("t_iso,t_rel_s,ciclu,ciclu_ms,rpm,tmot,marcaj,steaguri\n"
                                        "2026-01-02T12:00:00.1,0.1,1,10,800,90,,\n", encoding="utf-8")
        cod, out, _ = ruleaza(f.name, "--date", str(self.dir))
        self.assertEqual(cod, 0)
        self.assertIn("întreruptă", out)
        j = json.loads(ruleaza(f.name, "--date", str(self.dir), "--json")[1])
        self.assertEqual(j["randuri"], 1)
        self.assertEqual(j["coloane"]["rpm"]["min"], j["coloane"]["rpm"]["max"])

    def test_fara_sesiune_json(self):
        f = self.dir / "sesiuni" / "2026-01-03_120000_fara_json_necunoscut"
        f.mkdir()
        (f / "date_001.csv").write_text("t_iso,t_rel_s,ciclu,ciclu_ms,rpm,marcaj,steaguri\n"
                                        "2026-01-03T12:00:00.0,0.0,1,10,800,,\n"
                                        "2026-01-03T12:00:02.0,2.0,2,10,810,,\n", encoding="utf-8")
        cod, out, _ = ruleaza(f.name, "--date", str(self.dir))
        self.assertEqual(cod, 0)
        self.assertIn("lipsește sesiune.json", out)
        j = json.loads(ruleaza(f.name, "--date", str(self.dir), "--json")[1])
        self.assertEqual((j["randuri"], j["durata_s"], j["stare"]), (2, 2.0, "întreruptă"))

    def test_nu_modifica_nimic(self):
        dupa = self._instantaneu(self.dir)
        ruleaza(self.id, "--date", str(self.dir))
        ruleaza(self.id, "--date", str(self.dir), "--json")
        self.assertEqual(self._instantaneu(self.dir), dupa)

    def test_masoara_pe_date_cunoscute(self):
        f = self.dir / "sesiuni" / "2026-01-04_120000_fereastra_cald"
        f.mkdir()
        rand = ["t_iso,t_rel_s,ciclu,ciclu_ms,rpm,marcaj,steaguri"]
        for i in range(0, 101):  # 0..10 s, la 0,1 s; rpm 900, cade la 600 intre 5 si 5,5 s
            t = i / 10
            rand.append(f"2026-01-04T12:00:00,{t},{i},10,{600 if 5 <= t <= 5.5 else 900},,")
        (f / "date_001.csv").write_text("\n".join(rand) + "\n", encoding="utf-8")
        r = sesiuni.masoara(f.name, [5.0], ["rpm", "nu_exista"], self.dir)[0]
        self.assertNotIn("nu_exista", r)
        self.assertEqual((r["rpm"]["inainte"], r["rpm"]["min"], r["rpm"]["dupa"], r["rpm"]["cadere"]), (900, 600, 900, 300))
        self.assertEqual(r["rpm"]["t_min"], 5.0)


class TestRezumatReal(unittest.TestCase):
    """Test de fum pe datele reale din bmw-data; sarit daca folderul lipseste."""

    def setUp(self):
        if not (DIR_DATE / "sesiuni").is_dir():
            self.skipTest("bmw-data\\sesiuni lipsește")

    def test_toate_sesiunile(self):
        ls = sesiuni.lista()
        if not ls:
            self.skipTest("nicio sesiune")
        for s in ls:
            cod, out, err = ruleaza(s["id"])
            self.assertEqual(cod, 0, f"{s['id']}: {err}")
            self.assertIn(s["id"], out)
            json.loads(ruleaza(s["id"], "--json")[1])

    def test_sesiunea_mare(self):
        id_ = "2026-11-02_135337_drum_lung_oras_rece"
        if not (DIR_DATE / "sesiuni" / id_).is_dir():
            self.skipTest("sesiunea de referință lipsește")
        j = json.loads(ruleaza(id_, "--json")[1])
        self.assertEqual(j["randuri"], 13456)
        self.assertEqual(sum(1 for e in j["evenimente"] if e["tip"] == "marcaj"), 3)


if __name__ == "__main__":
    unittest.main()
