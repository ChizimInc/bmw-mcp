import unittest

from bmwdiag import flags
from bmwdiag.flags import MotorSteaguri, compara_erori, probleme_steag

CADERE = {"nume": "cadere_la_cuplare", "tip": "cadere", "camp": "rpm", "cu": 150, "in_s": 1.5,
          "conditii": ["pedala < 2", "viteza < 15"]}


def ruleaza(definitii, serie, pas=0.1):
    """serie: lista de dict-uri (un rand pe ciclu); intoarce [(t, nume, detalii)]."""
    m = MotorSteaguri(definitii)
    rez = []
    for i, rand in enumerate(serie):
        t = i * pas
        rez += [(round(t, 2), n, d) for n, d in m.evalueaza(t, rand)]
    return rez


class TestCadere(unittest.TestCase):
    def serie(self, adancime, pedala=0, viteza=0, durata_cadere_s=0.5):
        rpm = [800] * 10
        pasi = int(durata_cadere_s / 0.1)
        rpm += [800 - adancime * (i + 1) / pasi for i in range(pasi)]
        rpm += [800 - adancime] * 3 + [800] * 20
        return [{"rpm": r, "pedala": pedala, "viteza": viteza} for r in rpm]

    def test_cadere_mare_semnalata_o_data(self):
        rez = ruleaza([CADERE], self.serie(250))
        self.assertEqual(len(rez), 1)
        self.assertEqual(rez[0][1], "cadere_la_cuplare")
        self.assertIn("rpm a scăzut cu", rez[0][2])

    def test_cadere_mica_ignorata(self):
        self.assertEqual(ruleaza([CADERE], self.serie(120)), [])

    def test_cadere_lenta_ignorata(self):
        # 250 rpm in 4 s: nu e o cadere in 1,5 s
        self.assertEqual(ruleaza([CADERE], self.serie(250, durata_cadere_s=4.0)), [])

    def test_conditii(self):
        self.assertEqual(ruleaza([CADERE], self.serie(250, pedala=30)), [])   # accelerez: nu e cuplare
        self.assertEqual(ruleaza([CADERE], self.serie(250, viteza=60)), [])

    def test_conditie_din_grup_lent(self):
        # pedala vine doar in primul rand; ramane cunoscuta pentru randurile urmatoare
        serie = self.serie(250)
        for r in serie[1:]:
            del r["pedala"]
        self.assertEqual(len(ruleaza([CADERE], serie)), 1)

    def test_doua_cuplari_doua_steaguri(self):
        s = self.serie(250)
        self.assertEqual(len(ruleaza([CADERE], s + s)), 2)

    def test_zgomot_in_jurul_pragului_un_singur_steag(self):
        # revenire lenta cu oscilatii de +-5 rpm in jurul caderii de 150
        rpm = [800] * 10 + [640, 645, 652, 648, 655, 649, 653, 647] + [800] * 20
        self.assertEqual(len(ruleaza([CADERE], [{"rpm": r, "pedala": 0, "viteza": 0} for r in rpm])), 1)

    def test_celule_goale_ignorate(self):
        serie = self.serie(250)
        for r in serie[12:14]:
            del r["rpm"]
        self.assertEqual(len(ruleaza([CADERE], serie)), 1)


class TestAlteTipuri(unittest.TestCase):
    def test_trece_prag(self):
        d = {"nume": "tmot_prag", "tip": "trece_prag", "camp": "tmot", "praguri": [40, 60, 80]}
        serie = [{"tmot": t} for t in (35, 39.9, 40.1, 39.8, 40.2, 59, 61, 85)]  # zgomot la 40: histereza
        rez = ruleaza([d], serie)
        self.assertEqual(len(rez), 3)
        self.assertIn("peste 40", rez[0][2])
        self.assertIn("peste 60", rez[1][2])
        self.assertIn("peste 80", rez[2][2])
        rez = ruleaza([d], [{"tmot": 90}, {"tmot": 70}])
        self.assertIn("sub 80", rez[0][2])

    def test_prima_valoare_nu_e_trecere(self):
        d = {"nume": "p", "tip": "trece_prag", "camp": "tmot", "praguri": [40]}
        self.assertEqual(ruleaza([d], [{"tmot": 85}, {"tmot": 86}]), [])

    def test_sub_cu_timp(self):
        d = {"nume": "tensiune_mica", "tip": "sub", "camp": "ub", "valoare": 12.0, "timp_s": 3}
        scurt = [{"ub": 14}] + [{"ub": 11.5}] * 20 + [{"ub": 14}]            # 2 s: nu
        self.assertEqual(ruleaza([d], scurt), [])
        lung = [{"ub": 14}] + [{"ub": 11.5}] * 40 + [{"ub": 14}] + [{"ub": 11}] * 40
        rez = ruleaza([d], lung)
        self.assertEqual(len(rez), 2)  # o data pe episod
        self.assertIn("sub 12", rez[0][2])

    def test_peste(self):
        d = {"nume": "rpm_mare", "tip": "peste", "camp": "rpm", "valoare": 3000}
        self.assertEqual(len(ruleaza([d], [{"rpm": 2000}, {"rpm": 3100}, {"rpm": 3200}])), 1)


class TestValidare(unittest.TestCase):
    ALIAS = {"rpm", "pedala", "viteza", "tmot", "ub"}

    def test_valid(self):
        self.assertEqual(probleme_steag(CADERE, self.ALIAS), [])

    def test_invalide(self):
        cazuri = [
            ({"nume": "x", "tip": "necunoscut"}, "tip necunoscut"),
            ({"nume": "x", "tip": "cadere", "camp": "rpm", "cu": 150}, "in_s"),
            ({**CADERE, "camp": "nu_exista"}, "nu_exista"),
            ({**CADERE, "cu": -5}, "> 0"),
            ({**CADERE, "cu": "mult"}, "număr"),
            ({**CADERE, "conditii": ["pedala mica"]}, "pedala mica"),
            ({**CADERE, "conditii": ["frana < 1"]}, "alias"),
            ({**CADERE, "praguri": [1]}, "cheie necunoscută 'praguri'"),
            ({"nume": "x", "tip": "trece_prag", "camp": "tmot", "praguri": []}, "praguri"),
            ({"nume": "x", "tip": "eroare_noua"}, "automat"),
        ]
        for d, fragment in cazuri:
            with self.subTest(d=d):
                p = probleme_steag(d, self.ALIAS)
                self.assertTrue(any(fragment in x for x in p), p)

    def test_conditie(self):
        self.assertEqual(flags.parseaza_conditie("viteza<15"), ("viteza", "<", 15.0))
        self.assertEqual(flags.parseaza_conditie("fr1 >= -0.5"), ("fr1", ">=", -0.5))
        self.assertIsNone(flags.parseaza_conditie("import os"))


class TestComparaErori(unittest.TestCase):
    E1 = {"F_ORT_NR": 11107, "F_ORT_TEXT": "CDKPH2", "F_VORHANDEN_NR": 0, "F_VORHANDEN_TEXT": "nu acum"}

    def test_fara_schimbare(self):
        self.assertEqual(compara_erori([self.E1, {"JOB_STATUS": "OKAY"}], [self.E1, {"JOB_STATUS": "OKAY"}]), [])

    def test_eroare_noua(self):
        noua = {"F_ORT_NR": 11427, "F_ORT_TEXT": "CDKHSVSA2", "F_VORHANDEN_TEXT": "acum"}
        rez = compara_erori([self.E1], [self.E1, noua])
        self.assertEqual(len(rez), 1)
        self.assertIn("eroare nouă 2CA3 CDKHSVSA2", rez[0])

    def test_schimbare_stare(self):
        acum = {**self.E1, "F_VORHANDEN_NR": 1, "F_VORHANDEN_TEXT": "prezentă acum"}
        rez = compara_erori([self.E1], [acum])
        self.assertIn("și-a schimbat starea: nu acum → prezentă acum", rez[0])

    def test_eroare_disparuta_nu_e_steag(self):
        self.assertEqual(compara_erori([self.E1], []), [])


if __name__ == "__main__":
    unittest.main()
