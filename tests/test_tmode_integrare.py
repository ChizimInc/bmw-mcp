"""Integrare EDIABAS reala, fara masina: ECU-ul simulat TMODE prin EdiabasClient.

Se sare automat daca EDIABAS lipseste sau Python nu e pe 32 de biti.
"""
import os
import struct
import unittest

from bmwdiag.ediabas_client import EDIABAS_BIN, EdiabasClient

ARE_EDIABAS = os.path.isfile(os.path.join(EDIABAS_BIN, "api32.dll")) and struct.calcsize("P") == 4


@unittest.skipUnless(ARE_EDIABAS, "EDIABAS (api32.dll) sau Python 32-bit indisponibil")
class TestTmode(unittest.TestCase):
    def test_sesiune_persistenta_tmode(self):
        with EdiabasClient(ecu="TMODE") as c:
            for _ in range(3):  # aceeasi sesiune, mai multe joburi
                r = c.run("LESE_INTERFACE_TYP")
                self.assertTrue(r.ok, r.eroare)
                self.assertEqual(r.valori()["TYP"], "OBD")
                self.assertEqual(r.sistem.get("VARIANTE"), "TMODE")
            c.reset()
            self.assertTrue(c.run("LESE_INTERFACE_TYP").ok)

    def test_descriere_sgbd(self):
        # _JOBS nu comunica cu ECU, dar EDIABAS tot deschide interfata (COM1):
        # fara cablul in laptop da IFH-0018 (observat 02.11.2026)
        with EdiabasClient() as c:
            r = c.run("_JOBS")
        if not r.ok and "IFH-0018" in (r.eroare or ""):
            self.skipTest("cablul K+DCAN nu e conectat (IFH-0018)")
        self.assertTrue(r.ok, r.eroare)
        joburi = {s.get("JOBNAME") for s in r.seturi}
        self.assertIn("STATUS_MESSWERTE", joburi)
        self.assertIn("FS_LESEN", joburi)


if __name__ == "__main__":
    unittest.main()
