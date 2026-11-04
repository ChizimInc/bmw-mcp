"""Serverul web cu FakeSource, prin HTTP real pe un port liber (fara browser)."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bmwdiag import profiles
from bmwdiag.sources import FakeSource
from bmwdiag.webapp import Aplicatie, creeaza_server


class TestWebapp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        dir_profile = self.dir / "profiles"
        dir_profile.mkdir()
        (dir_profile / "eveniment_rapid.toml").write_text(
            (profiles.DIR_PROFILE / "eveniment_rapid.toml").read_text(encoding="utf-8"), encoding="utf-8")
        (dir_profile / "stricat.toml").write_text(
            'nume = "stricat"\necu = "MEV9N46L"\n[[grup]]\nnume = "g"\n  [[grup.citire]]\n'
            '  job = "FS_LOESCHEN"\n  valori = { x = "Y" }\n', encoding="utf-8")
        self.app = Aplicatie(sursa_tip="fake", dir_date=self.dir / "date", dir_profile=dir_profile,
                             fabrica_sursa=lambda ecu: FakeSource(ecu=ecu, latenta_ms=5))
        self.srv = creeaza_server(self.app, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.app.opreste_tot()
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def cere(self, cale, corp=None):
        date = None if corp is None else json.dumps(corp).encode("utf-8")
        req = urllib.request.Request(self.url + cale, data=date, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read(), r.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type")

    def j(self, cale, corp=None):
        cod, corp_r, _ = self.cere(cale, corp)
        return cod, json.loads(corp_r.decode("utf-8"))

    def test_pagina_si_fisiere_statice(self):
        cod, corp, tip = self.cere("/")
        self.assertEqual(cod, 200)
        self.assertIn("text/html", tip)
        text = corp.decode("utf-8")
        self.assertIn("nu folosi serverul MCP din chat", text)
        self.assertNotIn("<canvas", text)  # fara grafice
        for f in ("/app.js", "/style.css"):
            self.assertEqual(self.cere(f)[0], 200)
        self.assertEqual(self.cere("/../server.py")[0], 404)
        self.assertEqual(self.cere("/nu_exista")[0], 404)

    def test_vendor_uplot_local_si_doar_fisierele_cunoscute(self):
        cod, corp, tip = self.cere("/vendor/uPlot.iife.min.js")
        self.assertEqual(cod, 200)
        self.assertIn("javascript", tip)
        self.assertIn(b"uPlot", corp)
        cod, corp, tip = self.cere("/vendor/uPlot.min.css")
        self.assertEqual((cod, "text/css" in tip), (200, True))
        cod, corp, _ = self.cere("/vendor/LICENSE-uPlot.txt")
        self.assertEqual(cod, 200)
        self.assertIn(b"MIT", corp)
        for rau in ("/vendor/", "/vendor/VERSIUNE.txt", "/vendor/../app.js", "/vendor/%2e%2e/server.py",
                    "/vendor/uPlot.iife.min.js/..", "/vendor/nu_exista.js"):
            self.assertEqual(self.cere(rau)[0], 404, rau)

    def test_pagina_sesiuni_fara_cdn(self):
        cod, corp, _ = self.cere("/sesiuni.html")
        self.assertEqual(cod, 200)
        text = corp.decode("utf-8")
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        for f in ("/sesiuni_date.js", "/sesiuni.js", "/nume_ro.json"):
            self.assertEqual(self.cere(f)[0], 200, f)
        for f in ("vendor/uPlot.iife.min.js", "vendor/uPlot.min.css", "sesiuni_date.js"):
            self.assertIn(f, text)

    def test_profile_valide_si_invalide(self):
        cod, lista = self.j("/api/profile")
        self.assertEqual(cod, 200)
        pe_nume = {p["fisier"]: p for p in lista}
        self.assertEqual(len(pe_nume["eveniment_rapid"]["marcaje"]), 3)
        self.assertIn("FS_LOESCHEN", pe_nume["stricat"]["eroare"])
        cod, rez = self.j("/api/start", {"profil": "stricat"})
        self.assertEqual(cod, 400)
        self.assertIn("doar citire", rez["eroare"])
        self.assertFalse(self.app.activ)

    def test_ciclu_complet(self):
        cod, s = self.j("/api/stare")
        self.assertEqual((cod, s["stare"], s["activ"]), (200, "oprit", False))
        self.assertEqual(self.j("/api/marcaj", {"eticheta": "x"})[0], 409)
        self.assertEqual(self.j("/api/stop", {})[0], 409)

        cod, _ = self.j("/api/start", {"profil": "eveniment_rapid", "conditie": "cald", "nota": "proba"})
        self.assertEqual(cod, 200)
        self.assertEqual(self.j("/api/start", {"profil": "eveniment_rapid"})[0], 409)  # o singura sesiune
        time.sleep(1.0)
        cod, s = self.j("/api/stare")
        self.assertEqual(s["stare"], "inregistreaza")
        self.assertTrue(s["activ"])
        self.assertGreater(s["randuri"], 0)
        self.assertLess(s["ultima_reusita_s"], 2)
        self.assertEqual(s["valori"]["rpm"]["unitate"], "1/min")
        self.assertEqual([m["tasta"] for m in s["marcaje"]], ["1", "2", "3"])

        self.assertEqual(self.j("/api/marcaj", {"eticheta": "Cuplez ambreiajul"})[0], 200)
        self.assertEqual(self.j("/api/erori", {})[0], 202)
        time.sleep(0.5)

        cod, rez = self.j("/api/stop", {})
        self.assertEqual(cod, 200)
        folder = Path(rez["folder"])
        self.assertTrue(folder.name.endswith("_eveniment_rapid_cald"))
        self.assertTrue(list(folder.glob("erori_cerere_*.json")))
        evenimente = (folder / "evenimente.csv").read_text(encoding="utf-8")
        self.assertIn("Cuplez ambreiajul", evenimente)
        ses = json.loads((folder / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual((ses["nota"], ses["motiv_oprire"]), ("proba", "oprit din interfață"))

        cod, s = self.j("/api/stare")
        self.assertEqual((s["stare"], s["activ"], s["motiv_oprire"]), ("oprit", False, "oprit din interfață"))
        t1 = s["timp_s"]
        time.sleep(0.3)
        self.assertEqual(self.j("/api/stare")[1]["timp_s"], t1)  # timpul ramane inghetat dupa stop

    def test_inregistrarea_continua_fara_browser(self):
        self.j("/api/start", {"profil": "eveniment_rapid"})
        time.sleep(0.4)
        r1 = self.app.recorder.randuri
        time.sleep(1.0)  # nimeni nu citeste API-ul (browser inchis)
        r2 = self.app.recorder.randuri
        self.assertGreater(r2, r1)
        # "reincarcarea paginii": o cerere noua vede sesiunea in curs
        _, s = self.j("/api/stare")
        self.assertTrue(s["activ"])
        self.assertGreaterEqual(s["randuri"], r2)

    def test_jurnal_incremental(self):
        self.j("/api/start", {"profil": "eveniment_rapid"})
        time.sleep(0.5)
        _, d = self.j("/api/jurnal?de_la=0")
        self.assertTrue(any("Sesiune nouă" in t for _, t in d["linii"]))
        ultimul = d["ultimul"]
        _, d2 = self.j(f"/api/jurnal?de_la={ultimul}")
        self.assertTrue(all(n > ultimul for n, _ in d2["linii"]))

    def test_erori_fara_inregistrare(self):
        cod, rez = self.j("/api/erori", {})
        self.assertEqual(cod, 200)
        self.assertTrue(rez["ok"])
        self.assertIn("2B63", rez["rezumat"])
        self.assertTrue(Path(rez["fisier"]).is_file())

    def test_conditie_invalida(self):
        self.assertEqual(self.j("/api/start", {"profil": "eveniment_rapid", "conditie": "fierbinte"})[0], 400)

    def test_pagina_sesiuni_si_navigare(self):
        for cale, tip in (("/sesiuni.html", "text/html"), ("/sesiuni.js", "application/javascript"),
                          ("/nume_ro.json", "application/json")):
            cod, corp, t = self.cere(cale)
            self.assertEqual(cod, 200, cale)
            self.assertIn(tip, t)
        html = self.cere("/sesiuni.html")[1].decode("utf-8")
        self.assertNotIn("<canvas", html)  # fara grafice in etapa 7
        for pagina in ("/", "/sesiuni.html"):
            text = self.cere(pagina)[1].decode("utf-8")
            self.assertIn('href="/index.html"', text)
            self.assertIn('href="/sesiuni.html"', text)
            self.assertIn("Înregistrare", text)
        # fara CDN si fara resurse externe
        for cale in ("/sesiuni.html", "/sesiuni.js"):
            self.assertNotIn("http://", self.cere(cale)[1].decode("utf-8").replace("http://127", ""), cale)
            self.assertNotIn("https://", self.cere(cale)[1].decode("utf-8"), cale)

    def test_dictionar_nume_ro(self):
        cod, corp, _ = self.cere("/nume_ro.json")
        d = json.loads(corp.decode("utf-8"))
        for cheie in ("coloane", "stat", "joburi", "unitati", "steaguri"):
            self.assertIn(cheie, d)
        for alias, v in d["coloane"].items():
            self.assertTrue(v.get("eticheta"), alias)
            self.assertIn("unitate_afisata", v, alias)
            self.assertTrue(v.get("grup"), alias)
        self.assertEqual(d["coloane"]["rpm"]["eticheta"], "Turație")
        self.assertEqual(d["coloane"]["sarcina"]["eticheta"], "Sarcina motorului (umplere)")
        self.assertEqual(d["coloane"]["fr1"]["eticheta"], "Factor lambda banca 1")
        # fiecare alias din profilele livrate are denumire romaneasca, iar STAT_* din ele are eticheta
        for nume in profiles.lista(profiles.DIR_PROFILE):
            profil = profiles.incarca(nume, profiles.DIR_PROFILE)
            for grup in profil.grupuri:
                for citire in grup.citiri:
                    for alias, rezultat in citire.valori.items():
                        self.assertIn(alias, d["coloane"], f"{nume}: alias fara denumire: {alias}")
                        self.assertIn(rezultat, d["stat"], f"{nume}: rezultat fara eticheta: {rezultat}")


if __name__ == "__main__":
    unittest.main()
