"""EdiabasClient cu un PyDIABAS fals (fara EDIABAS si fara masina)."""
import unittest

from bmwdiag import guard
from bmwdiag.ediabas_client import EdiabasClient, decodeaza, din_dicts


class ResFals:
    def __init__(self, dicts):
        self._dicts = dicts

    def as_dicts(self):
        return self._dicts


class PyDIABASFals:
    def __init__(self, raspunsuri=None, exceptie=None):
        self.raspunsuri = raspunsuri or {}
        self.exceptie = exceptie
        self.apeluri = []
        self.starturi = 0
        self.resetari = 0
        self.inchis = False

    def start(self):
        self.starturi += 1

    def end(self):
        self.inchis = True

    def reset(self):
        self.resetari += 1

    def job(self, ecu, job, parametri, filtru):
        self.apeluri.append((ecu, job, parametri, filtru))
        if self.exceptie:
            raise self.exceptie
        return ResFals(self.raspunsuri[job])


SISTEM = {"OBJECT": "mev9n46l", "SAETZE": 1, "JOBNAME": "X", "VARIANTE": "MEV9N46L", "JOBSTATUS": ""}


class StateError(Exception):
    pass


class TestDecodare(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(decodeaza(b"OBD"), "OBD")
        self.assertEqual(decodeaza(b"\x83\x12\xf1"), "hex:8312f1")
        self.assertEqual(decodeaza({"A": [b"x", 1.5, None]}), {"A": ["x", 1.5, None]})

    def test_status(self):
        r = din_dicts("J", "E", [SISTEM, {"A": 1, "JOB_STATUS": "OKAY"}], 1.0)
        self.assertTrue(r.ok)
        self.assertEqual(r.valori()["A"], 1)
        r = din_dicts("J", "E", [SISTEM, {"JOB_STATUS": "ERROR_ECU_SERVICE_NOT_SUPPORTED"}], 1.0)
        self.assertFalse(r.ok)
        self.assertEqual(r.eroare, "ERROR_ECU_SERVICE_NOT_SUPPORTED")
        # TMODE nu intoarce JOB_STATUS: e considerat reusit
        r = din_dicts("J", "TMODE", [SISTEM, {"TYP": b"OBD"}], 1.0)
        self.assertTrue(r.ok)
        self.assertIsNone(r.status)
        self.assertEqual(r.valori(), {"TYP": "OBD"})
        # pe ECU-ul real lipsa lui JOB_STATUS e esec, jurnalizat ca avertisment
        r = din_dicts("J", "MEV9N46L", [SISTEM, {"STAT_NMOT_WERT": 700.0}], 1.0)
        self.assertFalse(r.ok)
        self.assertTrue(r.avertisment)
        self.assertIn("JOB_STATUS", r.eroare)


class TestClient(unittest.TestCase):
    def test_sesiune_persistenta(self):
        fals = PyDIABASFals({"STATUS_MESSWERTE": [SISTEM, {"STAT_NMOT_WERT": 708.5, "JOB_STATUS": "OKAY"}]})
        creari = []
        c = EdiabasClient(fabrica=lambda: creari.append(1) or fals)
        with c:
            for _ in range(5):
                r = c.run("STATUS_MESSWERTE", "STAT_NMOT_WERT;JOB_STATUS")
                self.assertTrue(r.ok)
                self.assertEqual(r.valori()["STAT_NMOT_WERT"], 708.5)
        self.assertEqual(len(creari), 1)
        self.assertEqual(fals.starturi, 1)
        self.assertTrue(fals.inchis)
        self.assertEqual(fals.apeluri[0], ("MEV9N46L", "STATUS_MESSWERTE", "", "STAT_NMOT_WERT;JOB_STATUS"))

    def test_garda_inainte_de_apel(self):
        fals = PyDIABASFals()
        with EdiabasClient(fabrica=lambda: fals) as c:
            for job in ("FS_LOESCHEN", "STEUERN_EKP", "FLASH_LESEN", "SET_X"):
                with self.assertRaises(guard.JobBlocat):
                    c.run(job)
        self.assertEqual(fals.apeluri, [])

    def test_eroare_comunicare_nu_ridica(self):
        fals = PyDIABASFals(exceptie=StateError("IFH-0018: INITIALIZATION ERROR"))
        with EdiabasClient(fabrica=lambda: fals) as c:
            r = c.run("STATUS_MESSWERTE")
        self.assertFalse(r.ok)
        self.assertIn("IFH-0018", r.eroare)

    def test_nepornit(self):
        r = EdiabasClient(fabrica=PyDIABASFals).run("IDENT")
        self.assertFalse(r.ok)
        self.assertIn("nu este pornita", r.eroare)

    def test_reset(self):
        fals = PyDIABASFals()
        c = EdiabasClient(fabrica=lambda: fals)
        c.reset()  # nepornit: porneste
        self.assertEqual(fals.starturi, 1)
        c.reset()
        self.assertEqual(fals.resetari, 1)
        c.stop()

    def test_ecu_per_apel(self):
        fals = PyDIABASFals({"LESE_INTERFACE_TYP": [SISTEM, {"TYP": b"OBD"}]})
        with EdiabasClient(fabrica=lambda: fals) as c:
            c.run("LESE_INTERFACE_TYP", ecu="TMODE")
        self.assertEqual(fals.apeluri[0][0], "TMODE")


if __name__ == "__main__":
    unittest.main()
