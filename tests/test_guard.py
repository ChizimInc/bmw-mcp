import unittest

from bmwdiag import guard


class TestGuard(unittest.TestCase):
    PERMISE = [
        "STATUS_MESSWERTE", "STATUS_FASTA2", "STATUS_LAUFUNRUHE", "STATUS_L_SONDE_2_H",
        "STATUS_GEMISCH", "STATUS_SYSTEMCHECK_LAMBDA_AUS",
        "FS_LESEN", "FS_LESEN_DETAIL", "AIF_LESEN", "ZIF_LESEN", "DATEN_REFERENZ_LESEN",
        "HARDWARE_REFERENZ_LESEN", "PRUEFSTEMPEL_LESEN", "SPEICHER_LESEN",
        "IDENT", "INFO", "LESE_INTERFACE_TYP",
        "_JOBS", "_JOBCOMMENTS", "_ARGUMENTS", "_RESULTS",
    ]
    REFUZATE = [
        # scriere / stergere / comanda
        "FS_LOESCHEN", "IS_LOESCHEN", "STEUERN_EKP", "STEUERN_ENDE", "STEUERN_VVT",
        "FLASH_SCHREIBEN", "FLASH_LESEN", "FLASH_PROGRAMMIER_STATUS_LESEN",
        "SET_PARAMETER", "SET_ECU_ADDRESS",
        "C_FG_SCHREIBEN", "C_FA_LOESCHEN", "CODIERUNG_SCHREIBEN", "AIF_SCHREIBEN",
        "ADAPTION_LOESCHEN", "SPEICHER_SCHREIBEN", "STATUS_RESET", "DIAGNOSE_RESET",
        "STATUS_WRITE_X", "STATUS_ERASE_X", "STATUS_DELETE_X", "PROGRAMMIER_LESEN",
        # trec de lista permisa doar prin cuvant interzis: tot refuzate
        "STATUS_STEUERN", "_LOESCHEN", "IDENT_SCHREIBEN", "LESE_SET_X",
        # nu sunt citiri
        "DIAGNOSE_ENDE", "DIAGNOSE_MODE", "SLEEP_MODE", "ENERGIESPARMODE", "",
        # litere mici: nu trec de lista permisa (refuz sigur)
        "fs_loeschen", "steuern_ekp", "status_messwerte",
        # trucuri de format
        "STATUS_MESSWERTE\n", "STATUS_MESSWERTE;FS_LOESCHEN", "STATUS MESSWERTE",
    ]

    def test_permise(self):
        for job in self.PERMISE:
            with self.subTest(job=job):
                self.assertTrue(guard.este_permis(job))
                self.assertEqual(guard.verifica(job), job)

    def test_refuzate(self):
        for job in self.REFUZATE:
            with self.subTest(job=job):
                self.assertFalse(guard.este_permis(job))
                with self.assertRaises(guard.JobBlocat):
                    guard.verifica(job)

    def test_tip_gresit(self):
        for job in (None, 123, b"STATUS_MESSWERTE"):
            with self.subTest(job=job):
                self.assertFalse(guard.este_permis(job))

    def test_motiv_in_romana(self):
        self.assertIn("interzis", guard.motiv_refuz("FS_LOESCHEN"))
        self.assertIn("lista", guard.motiv_refuz("DIAGNOSE_ENDE"))

    def test_aceleasi_reguli_ca_server(self):
        # server.py nu se importa aici (cere mcp); comparam textul regulilor
        from pathlib import Path
        sursa = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
        self.assertIn(guard.ALLOWED.pattern, sursa)
        self.assertIn(guard.DENIED.pattern, sursa)


if __name__ == "__main__":
    unittest.main()
