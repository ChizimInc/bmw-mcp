"""Interfata web locala a loggerului (biblioteca standard, fara framework).

    .venv\\Scripts\\python.exe -m bmwdiag.webapp [--sursa ediabas|fake] [--port 8765] [--deschide]

Inregistrarea ruleaza in firul recorderului: inchiderea browserului NU o opreste,
iar pagina reincarcata arata starea curenta (API-ul e citit la fiecare secunda).
"""
import argparse
import json
import sys
import threading
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, profiles, sistem
from .ediabas_client import ECU_IMPLICIT
from .jurnal import Jurnal
from .recorder import CONDITII, DIR_DATE, Recorder, _json, citeste_erori, creeaza_sursa

DIR_STATIC = Path(__file__).resolve().parent / "static"
FISIERE_STATICE = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
                   "/app.js": ("app.js", "application/javascript"), "/style.css": ("style.css", "text/css")}
AVERTISMENT_MCP = "Cât timp înregistrezi, nu folosi serverul MCP din chat."


class Aplicatie:
    """Starea aplicatiei: un singur recorder activ odata; jurnalul e comun tuturor sesiunilor."""

    def __init__(self, sursa_tip: str = "ediabas", dir_date=DIR_DATE, dir_profile=profiles.DIR_PROFILE,
                 fabrica_sursa=None, ecou=None, fake_tmot: float = 30.0):
        self.sursa_tip = sursa_tip
        self.dir_date = Path(dir_date)
        self.dir_profile = Path(dir_profile)
        self._fabrica = fabrica_sursa or (lambda ecu: creeaza_sursa(sursa_tip, ecu, fake_tmot=fake_tmot))
        self.jurnal = Jurnal(max_linii=200, ecou=ecou)
        self.recorder: Recorder | None = None
        self._lock = threading.Lock()

    @property
    def activ(self) -> bool:
        return self.recorder is not None and self.recorder.activ

    def stare(self) -> dict:
        if self.recorder is not None:
            s = self.recorder.stare()
        else:
            s = {"stare": "oprit", "profil": None, "conditie": None, "sursa": None, "marcaje": [], "timp_s": 0,
                 "randuri": 0, "cicluri_pe_s": 0, "ultima_reusita_s": None, "erori": 0, "folder": None,
                 "motiv_oprire": None, "steaguri": {}, "valori": {}}
        s.update(activ=self.activ, sursa_tip=self.sursa_tip, avertisment=AVERTISMENT_MCP, versiune=__version__)
        return s

    def profile(self) -> list[dict]:
        rez = []
        for nume in profiles.lista(self.dir_profile):
            try:
                p = profiles.incarca(nume, self.dir_profile)
                rez.append({"nume": p.nume, "fisier": nume, "descriere": p.descriere, "marcaje": p.marcaje})
            except profiles.ProfilInvalid as e:
                rez.append({"nume": nume, "fisier": nume, "eroare": str(e)})
        return rez

    def start(self, profil: str, conditie: str = "necunoscut", nota: str = "") -> tuple[int, dict]:
        with self._lock:
            if self.activ:
                return 409, {"eroare": "O înregistrare rulează deja. Oprește-o întâi."}
            if conditie not in CONDITII:
                return 400, {"eroare": f"Condiția trebuie să fie una din: {', '.join(CONDITII)}"}
            try:
                p = profiles.incarca(profil, self.dir_profile)
            except profiles.ProfilInvalid as e:
                self.jurnal.scrie(str(e), "eroare")
                return 400, {"eroare": str(e)}
            try:
                sursa = self._fabrica(p.ecu)
            except Exception as e:  # noqa: BLE001
                return 500, {"eroare": f"Nu pot crea sursa de date: {e}"}
            self.recorder = Recorder(p, sursa, dir_date=self.dir_date, conditie=conditie, nota=nota,
                                     jurnal=self.jurnal)
            self.recorder.porneste()
            return 200, {"ok": True}

    def stop(self) -> tuple[int, dict]:
        with self._lock:
            if not self.activ:
                return 409, {"eroare": "Nu rulează nicio înregistrare."}
            self.recorder.opreste("oprit din interfață")
            return 200, {"ok": True, "folder": str(self.recorder.folder)}

    def marcaj(self, eticheta: str) -> tuple[int, dict]:
        if not self.activ:
            return 409, {"eroare": "Marcajele merg doar în timpul înregistrării."}
        if not eticheta or not isinstance(eticheta, str):
            return 400, {"eroare": "Lipsește eticheta marcajului."}
        self.recorder.marcaj(eticheta[:200])
        return 200, {"ok": True}

    def erori(self) -> tuple[int, dict]:
        """In timpul inregistrarii: se citesc in bucla, la ciclul urmator. Altfel: sesiune scurta separata."""
        with self._lock:
            if self.activ:
                self.recorder.cere_erori()
                self.jurnal.scrie("Citirea erorilor a fost cerută; se face la ciclul următor.")
                return 202, {"ok": True, "in_inregistrare": True}
            self.jurnal.scrie("Citesc memoria de erori…")
            sursa = self._fabrica(ECU_IMPLICIT)
            try:
                sursa.start()
                date, rezumat, ok = citeste_erori(sursa, ECU_IMPLICIT)
            except Exception as e:  # noqa: BLE001
                date, rezumat, ok = {"eroare": str(e)}, f"citirea a eșuat: {e}", False
            finally:
                try:
                    sursa.stop()
                except Exception:  # noqa: BLE001
                    pass
            folder = self.dir_date / "erori_la_cerere"
            folder.mkdir(parents=True, exist_ok=True)
            cale = folder / f"erori_{datetime.now():%Y-%m-%d_%H%M%S}.json"
            _json(cale, date)
            self.jurnal.scrie(f"Erori (la cerere): {rezumat}. Salvat în {cale}", "info" if ok else "eroare")
            return 200, {"ok": ok, "rezumat": rezumat, "fisier": str(cale)}

    def opreste_tot(self, motiv: str = "serverul web s-a oprit", rapid: bool = False, timeout: float = 30):
        if self.activ:
            self.recorder.opreste(motiv, rapid=rapid, timeout=timeout)


def fa_handler(app: Aplicatie):
    class Handler(BaseHTTPRequestHandler):
        server_version = "bmwdiag/" + __version__

        def log_message(self, *args):  # fara zgomot in consola la fiecare cerere
            pass

        def _trimite(self, cod: int, corp: bytes, tip: str):
            self.send_response(cod)
            self.send_header("Content-Type", f"{tip}; charset=utf-8")
            self.send_header("Content-Length", str(len(corp)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corp)

        def _json(self, cod: int, obiect):
            self._trimite(cod, json.dumps(obiect, ensure_ascii=False, default=str).encode("utf-8"),
                          "application/json")

        def _corp(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                d = json.loads(self.rfile.read(n).decode("utf-8"))
                return d if isinstance(d, dict) else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/stare":
                return self._json(200, app.stare())
            if u.path == "/api/jurnal":
                try:
                    de_la = int(parse_qs(u.query).get("de_la", ["0"])[0])
                except ValueError:
                    de_la = 0
                linii = app.jurnal.de_la(de_la)
                return self._json(200, {"linii": linii, "ultimul": linii[-1][0] if linii else de_la})
            if u.path == "/api/profile":
                return self._json(200, app.profile())
            if u.path in FISIERE_STATICE:
                nume, tip = FISIERE_STATICE[u.path]
                return self._trimite(200, (DIR_STATIC / nume).read_bytes(), tip)
            self._json(404, {"eroare": "nu există"})

        def do_POST(self):
            u = urlparse(self.path)
            d = self._corp()
            if u.path == "/api/start":
                cod, rez = app.start(str(d.get("profil", "")), str(d.get("conditie", "necunoscut")),
                                     str(d.get("nota", "")))
            elif u.path == "/api/stop":
                cod, rez = app.stop()
            elif u.path == "/api/marcaj":
                cod, rez = app.marcaj(d.get("eticheta"))
            elif u.path == "/api/erori":
                cod, rez = app.erori()
            else:
                cod, rez = 404, {"eroare": "nu există"}
            self._json(cod, rez)

    return Handler


def creeaza_server(app: Aplicatie, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), fa_handler(app))
    srv.daemon_threads = True
    return srv


def main(argv=None):
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser(description="Logger EDIABAS cu interfață web locală (doar citire)")
    ap.add_argument("--sursa", choices=("ediabas", "fake"), default="ediabas")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 = accesibil și de pe telefon (implicit oprit)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--date", default=str(DIR_DATE))
    ap.add_argument("--deschide", action="store_true", help="deschide browserul")
    ap.add_argument("--fake-tmot", type=float, default=30.0,
                    help="sursa fake: temperatura motorului la start (ex. 90 = motor cald)")
    a = ap.parse_args(argv)

    blocare = sistem.BlocareInstanta(a.date)
    try:
        blocare.obtine(f"interfața web, port {a.port}")
    except sistem.InstantaDejaPornita as e:
        print(e, file=sys.stderr)
        return 3
    app = Aplicatie(sursa_tip=a.sursa, dir_date=a.date, ecou=print, fake_tmot=a.fake_tmot)
    try:
        srv = creeaza_server(app, a.host, a.port)
    except OSError as e:
        blocare.elibereaza()
        print(f"Nu pot porni serverul pe {a.host}:{a.port} ({e}). Portul e ocupat de alt program?",
              file=sys.stderr)
        return 1
    sistem.ctrl_break_ca_ctrl_c()
    sistem.la_inchiderea_consolei(lambda: app.opreste_tot("fereastra de consolă închisă", rapid=True, timeout=4))
    adresa = f"http://127.0.0.1:{a.port}"
    print(f"Logger pornit: {adresa}  (sursa: {a.sursa}). Ctrl+C oprește tot.")
    print("ATENȚIE: " + AVERTISMENT_MCP)
    if a.host != "127.0.0.1":
        print(f"ATENȚIE: interfața e accesibilă din rețea ({a.host}).")
    app.jurnal.scrie(f"Server web pornit ({adresa}, sursa {a.sursa})")
    if a.deschide:
        webbrowser.open(adresa)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Oprire (Ctrl+C): închid înregistrarea…")
        app.opreste_tot("Ctrl+C în fereastra loggerului")
    finally:
        app.opreste_tot()
        srv.server_close()
        blocare.elibereaza()
    return 0


if __name__ == "__main__":
    sys.exit(main())
