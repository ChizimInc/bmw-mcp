"""Etapa 4: o singura instanta, laptopul nu adoarme, oprire curata (Ctrl+Break real, fereastra inchisa)."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from bmwdiag import profiles, sistem
from bmwdiag.jurnal import Jurnal
from bmwdiag.recorder import Recorder
from bmwdiag.sources import FakeSource

RADACINA = Path(__file__).resolve().parents[1]
PE_WINDOWS = sys.platform == "win32"


def asteapta(conditie, secunde=20):
    t = time.monotonic()
    while time.monotonic() - t < secunde:
        rez = conditie()
        if rez:
            return rez
        time.sleep(0.1)
    return None


def sesiune(dir_date):
    folders = sorted((Path(dir_date) / "sesiuni").glob("*"))
    return folders[-1] if folders else None


class TestBlocare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_doua_instanta_refuzata(self):
        a = sistem.BlocareInstanta(self.dir).obtine("prima")
        self.assertIn(f"PID {os.getpid()} prima", a.cale.read_text(encoding="utf-8"))
        with self.assertRaises(sistem.InstantaDejaPornita) as cm:
            sistem.BlocareInstanta(self.dir).obtine("a doua")
        self.assertIn("rulează deja", str(cm.exception))
        a.elibereaza()
        b = sistem.BlocareInstanta(self.dir).obtine("dupa eliberare")
        b.elibereaza()

    def test_blocare_eliberata_daca_procesul_moare(self):
        cod = ("import sys,time; sys.path.insert(0, r'%s'); from bmwdiag import sistem; "
               "b = sistem.BlocareInstanta(r'%s').obtine('copil'); print('gata', flush=True); time.sleep(60)"
               % (RADACINA, self.dir))
        # python.exe din .venv e doar un lansator (alt PID); kill() trebuie sa loveasca procesul real
        python_real = getattr(sys, "_base_executable", sys.executable)
        p = subprocess.Popen([python_real, "-c", cod], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "gata")
            with self.assertRaises(sistem.InstantaDejaPornita) as cm:
                sistem.BlocareInstanta(self.dir).obtine()
            self.assertIn(f"PID {p.pid} copil", str(cm.exception))   # spune cine tine blocarea
            p.kill()          # ca o cadere: fara elibereaza()
            p.wait(10)
            sistem.BlocareInstanta(self.dir).obtine("dupa cadere").elibereaza()
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()


@unittest.skipUnless(PE_WINDOWS, "doar Windows")
class TestAdormire(unittest.TestCase):
    def test_set_thread_execution_state(self):
        self.assertTrue(sistem.impiedica_adormirea())
        self.assertTrue(sistem.permite_adormirea())

    def test_recorder_anunta_in_jurnal(self):
        with tempfile.TemporaryDirectory() as d:
            p = profiles.incarca("eveniment_rapid")
            p.instantaneu_la_start = []
            rec = Recorder(p, FakeSource(latenta_ms=5), dir_date=d, jurnal=Jurnal())
            rec.porneste()
            time.sleep(0.3)
            rec.opreste()
            self.assertIn("nu va adormi", (rec.folder / "jurnal.txt").read_text(encoding="utf-8"))


class TestOprireRapida(unittest.TestCase):
    """Ce face handlerul la inchiderea ferestrei de consola (apelat direct)."""

    def test_handler_fereastra_inchisa(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Recorder(profiles.incarca("eveniment_rapid"), FakeSource(latenta_ms=5), dir_date=d,
                           jurnal=Jurnal())
            rec.porneste()
            time.sleep(0.8)
            if PE_WINDOWS:
                self.assertTrue(sistem.la_inchiderea_consolei(
                    lambda: rec.opreste("fereastra de consolă închisă", rapid=True, timeout=4)))
                t0 = time.monotonic()
                self.assertEqual(sistem._handler_consola(sistem.CTRL_CLOSE_EVENT), 1)
                self.assertLess(time.monotonic() - t0, 4)     # Windows lasa ~5 s
                self.assertEqual(sistem._handler_consola(0), 0)  # Ctrl+C: tratarea obisnuita
            else:
                rec.opreste("fereastra de consolă închisă", rapid=True, timeout=4)
            ses = json.loads((rec.folder / "sesiune.json").read_text(encoding="utf-8"))
            self.assertEqual(ses["motiv_oprire"], "fereastra de consolă închisă")
            self.assertIsNotNone(ses["stop"])
            self.assertFalse((rec.folder / "erori_stop.json").exists())   # sarit, ca sa fie rapid
            self.assertEqual(sum(1 for _ in open(rec.folder / "date_001.csv", encoding="utf-8")) - 1,
                             ses["randuri"])


@unittest.skipUnless(PE_WINDOWS, "doar Windows")
class TestCtrlBreakReal(unittest.TestCase):
    """Proces separat, oprit cu Ctrl+Break (tratat ca Ctrl+C): sesiunea se inchide curat."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.p = None

    def tearDown(self):
        if self.p and self.p.poll() is None:
            self.p.kill()
            self.p.wait(10)
        self.tmp.cleanup()

    def porneste(self, *argumente):
        self.p = subprocess.Popen([sys.executable, *argumente, "--date", str(self.dir)], cwd=RADACINA,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    def ctrl_break(self):
        try:
            os.kill(self.p.pid, signal.CTRL_BREAK_EVENT)
        except OSError as e:
            self.skipTest(f"nu pot trimite Ctrl+Break în acest mediu ({e})")
        try:
            return self.p.wait(30)
        except subprocess.TimeoutExpired:
            self.skipTest("procesul nu a primit Ctrl+Break (consolă separată în acest mediu)")

    def test_recorder_consola(self):
        self.porneste("-m", "bmwdiag.recorder", "--profil", "eveniment_rapid", "--sursa", "fake")
        self.assertTrue(asteapta(lambda: sesiune(self.dir) and (sesiune(self.dir) / "date_001.csv").is_file()))
        time.sleep(1.5)
        # a doua instanta e refuzata cat timp prima ruleaza
        r = subprocess.run([sys.executable, "-m", "bmwdiag.recorder", "--profil", "eveniment_rapid",
                            "--sursa", "fake", "--date", str(self.dir)], cwd=RADACINA,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 3)
        self.assertIn("rulează deja", r.stderr)
        self.ctrl_break()
        ses = json.loads((sesiune(self.dir) / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["motiv_oprire"], "Ctrl+C")
        self.assertIsNotNone(ses["stop"])
        self.assertTrue((sesiune(self.dir) / "erori_stop.json").is_file())
        sistem.BlocareInstanta(self.dir).obtine().elibereaza()      # blocarea a fost eliberata

    def test_webapp(self):
        self.porneste("-m", "bmwdiag.webapp", "--sursa", "fake", "--port", "8799")
        url = "http://127.0.0.1:8799"

        def post(cale, corp):
            req = urllib.request.Request(url + cale, data=json.dumps(corp).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())

        def gata():
            try:
                return post("/api/start", {"profil": "eveniment_rapid", "conditie": "rece"})
            except OSError:
                return None
        self.assertTrue(asteapta(gata))
        time.sleep(1.5)
        self.ctrl_break()
        ses = json.loads((sesiune(self.dir) / "sesiune.json").read_text(encoding="utf-8"))
        self.assertEqual(ses["motiv_oprire"], "Ctrl+C în fereastra loggerului")
        self.assertGreater(ses["randuri"], 0)
        sistem.BlocareInstanta(self.dir).obtine().elibereaza()


if __name__ == "__main__":
    unittest.main()
