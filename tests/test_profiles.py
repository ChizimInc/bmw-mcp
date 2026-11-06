import tempfile
import unittest
from pathlib import Path

from bmwdiag import profiles

BAZA = """
nume = "t"
ecu = "MEV9N46L"
[[grup]]
nume = "rapid"
la_fiecare_s = 0
  [[grup.citire]]
  job = "STATUS_MESSWERTE"
  valori = { rpm = "STAT_NMOT_WERT" }
"""


class TestProfile(unittest.TestCase):
    def incarca_text(self, text):
        with tempfile.TemporaryDirectory() as d:
            cale = Path(d) / "p.toml"
            cale.write_text(text, encoding="utf-8")
            return profiles.incarca(cale)

    def test_profil_livrat(self):
        p = profiles.incarca("eveniment_rapid")
        self.assertEqual(p.ecu, "MEV9N46L")
        self.assertEqual([g.nume for g in p.grupuri], ["rapid", "lent"])
        self.assertIn("sarcina", p.aliasuri())
        self.assertEqual(len(p.aliasuri()), len(set(p.aliasuri())))
        self.assertEqual([m["tasta"] for m in p.marcaje], ["1", "2", "3"])
        self.assertIn("eveniment_rapid", profiles.lista())

    def test_marcaje_standard(self):
        p = self.incarca_text("marcaje_standard = true\n" + BAZA)
        self.assertEqual([m["tasta"] for m in p.marcaje], ["1", "2", "3"])
        self.assertEqual(p.marcaje[0]["eticheta"], "Cuplez ambreiajul")
        p = self.incarca_text("marcaje_standard = true\n" + BAZA + '\n[[marcaj]]\neticheta = "Altul"\ntasta = "4"\n')
        self.assertEqual([m["tasta"] for m in p.marcaje], ["1", "2", "3", "4"])
        self.assertEqual(self.incarca_text(BAZA).marcaje, [])
        self.assertRespins("marcaje_standard = true\n" + BAZA + '\n[[marcaj]]\neticheta = "X"\ntasta = "2"\n', "tasta '2'")
        self.assertRespins('marcaje_standard = "da"\n' + BAZA, "marcaje_standard")

    def test_profil_start_stop(self):
        from bmwdiag import guard
        p = profiles.incarca("start_stop")
        self.assertEqual(p.ecu, "MEV9N46L")
        self.assertEqual(len(p.aliasuri()), len(set(p.aliasuri())))
        self.assertTrue(all(guard.este_permis(j) for j in p.toate_joburile()))
        rapid = next(g for g in p.grupuri if g.nume == "rapid")
        self.assertEqual(rapid.la_fiecare_s, 0)
        self.assertEqual([c.job for c in rapid.citiri], ["STATUS_MESSWERTE", "STATUS_VVT", "STATUS_FASTA2"])
        self.assertEqual(p.min_ciclu_ms, 0)
        self.assertEqual([m["tasta"] for m in p.marcaje][:3], ["1", "2", "3"])
        self.assertEqual(p.marcaje[0]["eticheta"], "Cuplez ambreiajul")

    def test_minim(self):
        p = self.incarca_text(BAZA)
        self.assertEqual(p.aliasuri(), ["rpm"])
        self.assertTrue(p.erori_la_start)

    def test_toate_senzorii_si_rotativ(self):
        p = self.incarca_text('toate_senzorii = true\n' + BAZA.replace('la_fiecare_s = 0', 'la_fiecare_s = 0\nrotativ = true'))
        self.assertTrue(p.toate_senzorii)
        self.assertTrue(p.grupuri[0].rotativ)
        p = self.incarca_text(BAZA)
        self.assertFalse(p.toate_senzorii)
        self.assertFalse(p.grupuri[0].rotativ)
        self.assertRespins('toate_senzorii = "da"\n' + BAZA, "toate_senzorii")
        self.assertRespins(BAZA.replace('la_fiecare_s = 0', 'la_fiecare_s = 0\nrotativ = "da"'), "rotativ")

    def assertRespins(self, text, *fragmente):
        with self.assertRaises(profiles.ProfilInvalid) as cm:
            self.incarca_text(text)
        for f in fragmente:
            self.assertIn(f, str(cm.exception))

    def test_job_refuzat_de_garda(self):
        self.assertRespins(BAZA.replace("STATUS_MESSWERTE", "STEUERN_EKP"), "STEUERN_EKP", "doar citire")
        self.assertRespins('instantaneu_la_start = ["FS_LOESCHEN"]\n' + BAZA, "FS_LOESCHEN")

    def test_chei_necunoscute(self):
        # o greseala de tipar nu trebuie ignorata in tacere
        self.assertRespins("segment_minut = 10\n" + BAZA, "'segment_minut'")
        self.assertRespins(BAZA.replace("la_fiecare_s", "la_fiecare"), "'la_fiecare'")
        self.assertRespins(BAZA + '  rezultat = "X"\n', "'rezultat'")

    def test_alias_duplicat_si_rezervat(self):
        dublu = BAZA + '  [[grup.citire]]\n  job = "STATUS_FASTA2"\n  valori = { rpm = "STAT_RL_WERT" }\n'
        self.assertRespins(dublu, "'rpm' e folosit de două ori")
        self.assertRespins(BAZA.replace("rpm =", "ciclu ="), "rezervat")
        self.assertRespins(BAZA.replace("rpm =", "Rpm ="), "litere mici")

    def test_campuri_lipsa(self):
        self.assertRespins(BAZA.replace('ecu = "MEV9N46L"', ""), "'ecu'")
        self.assertRespins('nume = "x"\necu = "MEV9N46L"\n', "[[grup]]")
        self.assertRespins(BAZA.replace("la_fiecare_s = 0", "la_fiecare_s = -1"), "la_fiecare_s")

    def test_msv70_respins(self):
        self.assertRespins(BAZA.replace("MEV9N46L", "MSV70"), "MSV70")

    def test_toml_stricat_si_lipsa(self):
        self.assertRespins("nume = ", "TOML")
        with self.assertRaises(profiles.ProfilInvalid):
            profiles.incarca("nu_exista_asa_ceva")

    def test_steag_pe_camp_inexistent(self):
        self.assertRespins(BAZA + '[[steag]]\nnume = "s"\ntip = "sub"\ncamp = "xyz"\n', "xyz")

    def test_toate_problemele_odata(self):
        text = BAZA.replace("STATUS_MESSWERTE", "FS_LOESCHEN").replace("MEV9N46L", "MSV70")
        self.assertRespins(text, "FS_LOESCHEN", "MSV70")


if __name__ == "__main__":
    unittest.main()
