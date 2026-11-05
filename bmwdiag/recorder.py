"""Bucla de citire si scrierea folderului de sesiune (PLAN_LOGGER.md, sectiunile 7 si 8).

Consola:
    .venv\\Scripts\\python.exe -m bmwdiag.recorder --profil eveniment_rapid --sursa fake
Taste in consola: 1-9 = marcajele din profil, q = stop (sau Ctrl+C).
"""
import argparse
import atexit
import collections
import csv
import json
import os
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import __version__, flags, profiles, sistem
from .jurnal import Jurnal
from .mesaje import explica
from .sources import EdiabasSource, FakeSource, ReplaySource, _nume_unitate

# Folderul de date: variabila de mediu BMW_DATA_DIR sau, implicit, Documents\bmw-data din profilul utilizatorului.
DIR_DATE = Path(os.environ.get("BMW_DATA_DIR") or (Path.home() / "Documents" / "bmw-data"))
CONDITII = ("rece", "cald", "necunoscut")
BUFFER_LIVE_MAX = 6000       # randurile pastrate in memorie in modul live (~15 min la 7 cicluri/s)
INACTIV_LIVE_S = 60          # fara nicio cerere de la pagina, citirea live se opreste singura
LIMITA_RANDURI_LIVE = 5000   # cel mult atatea randuri intr-un raspuns /api/live
PAUZA_FARA_REUSITA_S = 0.5   # nu invartim bucla in gol cand nu raspunde nimic
CICLURI_PANA_LA_PIERDERE = 3  # cicluri consecutive fara nicio citire reusita -> conexiune_pierduta
PAUZE_RECONECTARE = (1, 2, 5)  # secunde inainte de fiecare reset(); apoi ramane la ultima
REPETARE_EROARE_S = 10       # aceeasi eroare a aceluiasi job se scrie in jurnal cel mult o data la 10 s


def _acum_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _json(cale: Path, obiect):
    cale.write_text(json.dumps(obiect, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def citeste_erori(sursa, ecu: str) -> tuple[dict, str, bool]:
    """FS_LESEN + FS_LESEN_DETAIL pentru fiecare eroare. Intoarce (date pentru JSON, rezumat, ok)."""
    r = sursa.run("FS_LESEN", ecu=ecu)
    detalii = {}
    if not r.ok:
        return {"t_iso": _acum_iso(), "fs_lesen": asdict(r), "detalii": {}}, \
            f"citirea a eșuat: {explica(r.eroare)}", False
    coduri = []
    for s in r.seturi:
        nr = s.get("F_ORT_NR")
        if isinstance(nr, (int, float)):
            detalii[str(int(nr))] = asdict(sursa.run("FS_LESEN_DETAIL", parametri=str(int(nr)), ecu=ecu))
            coduri.append(f"{int(nr):04X} {s.get('F_ORT_TEXT', '')}".strip())
    rezumat = f"{len(coduri)}" + (": " + "; ".join(coduri) if coduri else "")
    return {"t_iso": _acum_iso(), "fs_lesen": asdict(r), "detalii": detalii}, rezumat, True


class Recorder:
    def __init__(self, profil: profiles.Profil, sursa, dir_date=DIR_DATE, conditie: str = "necunoscut",
                 nota: str = "", jurnal: Jurnal | None = None, ceas=time.monotonic, scrie: bool = True,
                 inactiv_s: float = INACTIV_LIVE_S):
        """scrie=False: mod LIVE. Aceeasi bucla de citire (garda, reconectare, steaguri), dar nu scrie NIMIC pe disc
        (fara folder, CSV, sesiune.json, instantaneu sau citiri de erori); randurile stau intr-un buffer circular
        in memorie si citirea se opreste singura dupa inactiv_s secunde fara cereri la date_live()."""
        if conditie not in CONDITII:
            raise ValueError(f"conditie trebuie sa fie una din {CONDITII}")
        self.scrie = scrie
        self.inactiv_s = inactiv_s
        self.buffer: collections.deque = collections.deque(maxlen=BUFFER_LIVE_MAX)
        self.evenimente_mem: collections.deque = collections.deque(maxlen=500)   # (nr, t_rel_s, tip, detalii, t_iso)
        self._nr_ev = 0
        self._ultima_cerere = None
        self._text_ok = "inregistreaza" if scrie else "live"
        self.profil = profil
        self.sursa = sursa
        self.dir_date = Path(dir_date)
        self.conditie = conditie
        self.nota = nota
        self.jurnal = jurnal or Jurnal()
        self._ceas = ceas
        self._oprire = threading.Event()
        self._motiv_oprire = None
        self._lock = threading.Lock()
        self._marcaje_in_asteptare: list[str] = []
        self._erori_cerute = False
        self._rapid = False
        self._fara_somn = False
        self._erori_baza = None             # seturile ultimei citiri FS_LESEN reusite
        self.motor_steaguri = flags.MotorSteaguri(profil.steaguri)
        self._steaguri_in_asteptare: list[str] = []
        self.numar_steaguri = collections.Counter()
        self._cicluri_fara_reusita = 0
        self._conexiune_pierduta = False
        self._pas_reconectare = 0
        self._fir = None
        self.folder: Path | None = None
        self.stare_text = "oprit"
        self.coloane = ["t_iso", "t_rel_s", "ciclu", "ciclu_ms"] + profil.aliasuri() + ["marcaj", "steaguri"]
        # alias -> {job, rezultat, unitate}
        self.mapare = {a: {"job": c.job, "rezultat": r, "unitate": ""}
                       for g in profil.grupuri for c in g.citiri for a, r in c.valori.items()}
        self._unitati_cerute: set[str] = set()
        self.ultimele: dict[str, object] = {}
        self.randuri = 0
        self.cicluri = 0
        self.erori = 0
        self.statistici_joburi = collections.defaultdict(lambda: {"n": 0, "ok": 0, "erori": 0, "ms_total": 0.0})
        self._ultima_eroare: dict[str, tuple[str, float, int]] = {}   # job -> (text, t ultima scriere, repetari)
        self._sfarsit_cicluri = collections.deque(maxlen=200)
        self._t0 = None
        self._t_final = None     # durata inghetata la stop
        self._t_ultima_reusita = None
        self._csv = None
        self._csv_fh = None
        self._segment = 0
        self._t_segment = 0.0
        self._t_fsync = 0.0
        self._ev_fh = None
        self._ev = None
        self._start_iso = None

    # ------------------------------------------------------------ API public
    def porneste(self):
        """Porneste inregistrarea intr-un fir separat."""
        self._fir = threading.Thread(target=self.ruleaza, name="recorder", daemon=True)
        self._fir.start()

    def opreste(self, motiv: str = "oprit de utilizator", asteapta: bool = True, rapid: bool = False,
                timeout: float = 30):
        """rapid=True: fara citirea erorilor la stop (ex. fereastra inchisa: Windows lasa ~5 s)."""
        if self._motiv_oprire is None:
            self._motiv_oprire = motiv
        if rapid:
            self._rapid = True
        self._oprire.set()
        if asteapta and self._fir and self._fir is not threading.current_thread():
            self._fir.join(timeout=timeout)

    def marcaj(self, eticheta: str):
        with self._lock:
            self._marcaje_in_asteptare.append(eticheta)

    def cere_erori(self):
        """Citeste memoria de erori la inceputul ciclului urmator (in firul buclei)."""
        self._erori_cerute = True

    @property
    def activ(self) -> bool:
        return self._fir is not None and self._fir.is_alive()

    # ------------------------------------------------------------ modul live
    @staticmethod
    def _numar(x):
        if isinstance(x, bool):
            return None
        if isinstance(x, (int, float)):
            return x
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def date_live(self, de_la_ciclu: int = 0, coloane: list[str] | None = None, de_la_ev: int = 0) -> dict:
        """Randurile noi din buffer (ciclu > de_la_ciclu), pe coloane, ca /api/sesiuni/<id>/date: {"t":[...], alias:[...]}
        cu None pentru celule goale sau netextuale. reset=True: cursorul a iesit din buffer (randuri pierdute).
        Fiecare apel reinnoieste temporizatorul de inactivitate."""
        self._ultima_cerere = self._ceas()
        coloane = list(self.mapare) if coloane is None else coloane
        for c in coloane:
            if c not in self.mapare:
                raise ValueError(f"Coloană necunoscută: {c!r}")
        with self._lock:
            noi = []
            for r in reversed(self.buffer):
                if r["ciclu"] <= de_la_ciclu:
                    break
                noi.append(r)
            noi.reverse()
            prima = self.buffer[0]["ciclu"] if self.buffer else 0
            reset = bool(de_la_ciclu and self.buffer and prima > de_la_ciclu + 1)
            if len(noi) > LIMITA_RANDURI_LIVE:
                noi, reset = noi[-LIMITA_RANDURI_LIVE:], True
            ev = [{"nr": n, "t": t, "tip": tip, "detalii": d} for n, t, tip, d, _ in self.evenimente_mem if n > de_la_ev]
            ev_ultim = self._nr_ev
        rez = {"t": [r["t_rel_s"] for r in noi], "ciclu": [r["ciclu"] for r in noi]}
        for c in coloane:
            rez[c] = [self._numar(r.get(c)) for r in noi]
        st = self.stare()
        rez.update(ciclu_ultim=noi[-1]["ciclu"] if noi else de_la_ciclu, reset=reset, evenimente=ev, ev_ultim=ev_ultim,
                   marcaj=[r.get("marcaj", "") for r in noi], steaguri=[r.get("steaguri", "") for r in noi],
                   unitati={a: m["unitate"] for a, m in self.mapare.items()},
                   **{k: st[k] for k in ("stare", "mod", "timp_s", "cicluri_pe_s", "ultima_reusita_s", "erori",
                                          "steaguri_total", "motiv_oprire") if k in st})
        return rez

    def exporta_buffer(self, secunde: float, dir_date=None, conditie: str = "necunoscut", nota: str = "") -> Path:
        """Salveaza EXPLICIT ultimele `secunde` din buffer ca sesiune normala (singura scriere a modului live).
        Folosibila si dupa oprirea citirii, cat timp recorderul exista."""
        if self.scrie:
            raise ValueError("Exportul se face doar din modul live.")
        if conditie not in CONDITII:
            raise ValueError(f"conditia trebuie sa fie una din {CONDITII}")
        if not (isinstance(secunde, (int, float)) and not isinstance(secunde, bool) and secunde > 0):
            raise ValueError("Numărul de secunde trebuie să fie pozitiv.")
        with self._lock:
            randuri, evenimente = list(self.buffer), list(self.evenimente_mem)
        if not randuri:
            raise ValueError("Bufferul live e gol: nu am ce salva.")
        t_sf = randuri[-1]["t_rel_s"]
        randuri = [r for r in randuri if r["t_rel_s"] >= t_sf - secunde]
        t0 = randuri[0]["t_rel_s"]
        baza = Path(dir_date or self.dir_date) / "sesiuni"
        nume = f"{datetime.now():%Y-%m-%d_%H%M%S}_{self.profil.nume}_{conditie}"
        folder, k = baza / nume, 2
        while folder.exists():
            folder, k = baza / f"{nume}_{k}", k + 1
        folder.mkdir(parents=True)
        with open(folder / "date_001.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=self.coloane, extrasaction="ignore")
            w.writeheader()
            for r in randuri:
                w.writerow({**r, "t_rel_s": f"{r['t_rel_s'] - t0:.3f}", "ciclu_ms": f"{r['ciclu_ms']:.1f}"})
        ev_fereastra = [e for e in evenimente if t0 <= e[1] <= t_sf]
        with open(folder / "evenimente.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t_iso", "t_rel_s", "tip", "detalii"])
            w.writerow([randuri[0]["t_iso"], "0.000", "stare",
                        f"export din citirea live: ultimele {secunde:g} s (profil={self.profil.nume})"])
            for _, t, tip, detalii, iso in ev_fereastra:
                w.writerow([iso, f"{t - t0:.3f}", tip, detalii])
        steaguri = collections.Counter(d.split(":", 1)[0].strip() for _, _, tip, d, _ in ev_fereastra if tip == "steag")
        durata = t_sf - t0
        _json(folder / "coloane.json", self.mapare)
        _json(folder / "sesiune.json", {
            "versiune_aplicatie": __version__, "profil": self.profil.nume, "profil_toml": self.profil.sursa_toml,
            "conditie": conditie, "nota": nota, "sursa": type(self.sursa).__name__, "ecu": self.profil.ecu,
            "start": randuri[0]["t_iso"], "stop": randuri[-1]["t_iso"], "segmente": 1, "randuri": len(randuri),
            "motiv_oprire": "exportat din citirea live", "origine": "live",
            "statistici": {"durata_s": round(durata, 2), "cicluri": len(randuri), "randuri": len(randuri), "erori": 0,
                           "steaguri": dict(steaguri),
                           "cicluri_pe_s": round(len(randuri) / durata, 3) if durata > 0 else 0, "joburi": {}},
        })
        self.jurnal.scrie(f"Salvat din live: ultimele {secunde:g} s ({len(randuri)} rânduri) în {folder}")
        return folder

    def t_rel(self) -> float:
        if self._t_final is not None:
            return self._t_final
        return 0.0 if self._t0 is None else self._ceas() - self._t0

    def stare(self) -> dict:
        with self._lock:
            acum = self._ceas()
            recente = [t for t in self._sfarsit_cicluri if acum - t <= 10]
            if len(recente) >= 2:
                cps = (len(recente) - 1) / max(recente[-1] - recente[0], 1e-6)
            else:
                cps = 0.0
            return {
                "stare": self.stare_text, "mod": "inregistrare" if self.scrie else "live",
                "profil": self.profil.nume, "conditie": self.conditie,
                "sursa": type(self.sursa).__name__, "marcaje": self.profil.marcaje,
                "timp_s": round(self.t_rel(), 1), "randuri": self.randuri, "cicluri_pe_s": round(cps, 2),
                "ultima_reusita_s": None if self._t_ultima_reusita is None
                else round(acum - self._t_ultima_reusita, 1),
                "erori": self.erori, "folder": str(self.folder) if self.folder else None,
                "motiv_oprire": self._motiv_oprire if self.stare_text == "oprit" else None,
                "steaguri": dict(self.numar_steaguri), "steaguri_total": sum(self.numar_steaguri.values()),
                "valori": {a: {"valoare": self.ultimele.get(a), "unitate": self.mapare[a]["unitate"]}
                           for a in self.mapare},
            }

    def statistici(self) -> dict:
        durata = self.t_rel()
        return {
            "durata_s": round(durata, 2), "cicluri": self.cicluri, "randuri": self.randuri, "erori": self.erori,
            "steaguri": dict(self.numar_steaguri),
            "cicluri_pe_s": round(self.cicluri / durata, 3) if durata > 0 else 0,
            "joburi": {j: {"n": s["n"], "ok": s["ok"], "erori": s["erori"],
                           "ms_medie": round(s["ms_total"] / s["n"], 1) if s["n"] else None}
                       for j, s in self.statistici_joburi.items()},
        }

    # ------------------------------------------------------------ bucla
    def ruleaza(self):
        # starea anti-somn e per fir: o tine firul care inregistreaza, cat timp inregistreaza
        fara_somn = self._fara_somn = sistem.impiedica_adormirea()
        try:
            self._pregateste()
            if not self._oprire.is_set():
                self.stare_text = self._text_ok
                self._bucla()
        except Exception as e:  # noqa: BLE001
            self.stare_text = "eroare"
            self._motiv_oprire = self._motiv_oprire or f"eroare: {type(e).__name__}: {e}"
            self.jurnal.scrie(f"Oprire neașteptată: {type(e).__name__}: {e}", "eroare")
        finally:
            try:
                self._incheie()
            finally:
                if fara_somn:
                    sistem.permite_adormirea()

    def _pregateste(self):
        self.stare_text = "porneste"
        self._t0 = self._ceas()
        self._ultima_cerere = self._t0
        self._start_iso = _acum_iso()
        if not self.scrie:
            self.jurnal.scrie(f"Citire LIVE (nu se salvează nimic): profil '{self.profil.nume}', "
                              f"sursa {type(self.sursa).__name__}")
            if self._fara_somn:
                self.jurnal.scrie("Laptopul nu va adormi cât timp citești live.")
            try:
                self.sursa.start()
            except Exception as e:  # noqa: BLE001
                self.jurnal.scrie(f"Nu pot porni sesiunea de citire: {explica(f'{type(e).__name__}: {e}')}", "eroare")
                self._motiv_oprire = "sesiunea de citire nu a pornit"
                self._oprire.set()
            return
        baza = self.dir_date / "sesiuni"
        nume = f"{datetime.now():%Y-%m-%d_%H%M%S}_{self.profil.nume}_{self.conditie}"
        folder, k = baza / nume, 2
        while folder.exists():
            folder, k = baza / f"{nume}_{k}", k + 1
        folder.mkdir(parents=True)
        self.folder = folder
        self.jurnal.deschide_fisier(folder / "jurnal.txt")
        self._ev_fh = open(folder / "evenimente.csv", "w", newline="", encoding="utf-8")
        self._ev = csv.writer(self._ev_fh)
        self._ev.writerow(["t_iso", "t_rel_s", "tip", "detalii"])
        self._scrie_sesiune()
        self._scrie_coloane()
        self._eveniment("stare", f"start profil={self.profil.nume} sursa={type(self.sursa).__name__}")
        self.jurnal.scrie(f"Sesiune nouă: {folder}")
        self.jurnal.scrie(f"Profil '{self.profil.nume}', condiție {self.conditie}, sursa {type(self.sursa).__name__}")
        if self._fara_somn:
            self.jurnal.scrie("Laptopul nu va adormi cât timp înregistrezi (ecranul se poate stinge; "
                              "nu închide capacul).")
        try:
            self.sursa.start()
        except Exception as e:  # noqa: BLE001
            self.jurnal.scrie(f"Nu pot porni sesiunea de citire: {explica(f'{type(e).__name__}: {e}')}", "eroare")
            self._motiv_oprire = "sesiunea de citire nu a pornit"
            self._oprire.set()
            return
        if self.profil.erori_la_start:
            self._citeste_erori("start")
        if self.profil.instantaneu_la_start:
            self._instantaneu()
        self._segment_nou()

    def _bucla(self):
        p = self.profil
        ultima_grup = {}
        ultima_erori = self._ceas()
        while not self._oprire.is_set():
            acum = self._ceas()
            if not self.scrie:
                if acum - self._ultima_cerere > self.inactiv_s:
                    self.opreste(f"inactivitate: nicio cerere de la pagină în {self.inactiv_s:g} s", asteapta=False)
                    break
            elif p.durata_max_minute and self.t_rel() >= p.durata_max_minute * 60:
                self.opreste("durata maximă atinsă", asteapta=False)
                break
            if self.scrie and p.segment_minute and acum - self._t_segment >= p.segment_minute * 60:
                self._segment_nou()
            if self.scrie and p.erori_interval_minute and acum - ultima_erori >= p.erori_interval_minute * 60:
                self._citeste_erori(f"{self.t_rel():.0f}")
                ultima_erori = acum
            if self._erori_cerute and self.scrie:
                self._erori_cerute = False
                self._citeste_erori(f"cerere_{self.t_rel():.0f}")
            self.sursa.ciclu_nou()
            if getattr(self.sursa, "epuizat", False):
                self.opreste("sfârșitul înregistrării (replay)", asteapta=False)
                break
            t_ciclu = self._ceas()
            t_iso = _acum_iso()
            rand, reusite = {}, 0
            for g in p.grupuri:
                ult = ultima_grup.get(g.nume)
                if ult is not None and g.la_fiecare_s > 0 and t_ciclu - ult < g.la_fiecare_s:
                    continue
                ultima_grup[g.nume] = t_ciclu
                for c in g.citiri:
                    reusite += self._citeste(c, rand)
            ciclu_ms = (self._ceas() - t_ciclu) * 1000
            with self._lock:
                marcaje, self._marcaje_in_asteptare = self._marcaje_in_asteptare, []
                self.cicluri += 1
                self._sfarsit_cicluri.append(self._ceas())
                if reusite:
                    self._t_ultima_reusita = self._ceas()
                self.ultimele.update(rand)
            for m in marcaje:
                self.jurnal.scrie(f"Marcaj: {m}")
                self._eveniment("marcaj", m)
            for nume, detalii in self.motor_steaguri.evalueaza(t_ciclu - self._t0, rand):
                self._steag(nume, detalii)
            self._stare_conexiune(reusite)
            with self._lock:
                steaguri, self._steaguri_in_asteptare = self._steaguri_in_asteptare, []
            rand.update({"t_iso": t_iso, "t_rel_s": f"{t_ciclu - self._t0:.3f}", "ciclu": self.cicluri,
                         "ciclu_ms": f"{ciclu_ms:.1f}", "marcaj": ";".join(marcaje), "steaguri": ";".join(steaguri)})
            self._scrie_rand(rand)
            if self.scrie and p.cicluri_max and self.cicluri >= p.cicluri_max:
                self.opreste(f"gata: {p.cicluri_max} cicluri citite", asteapta=False)
                break
            if self._conexiune_pierduta:
                self._reconecteaza()
            elif p.min_ciclu_ms and ciclu_ms < p.min_ciclu_ms:
                self._oprire.wait((p.min_ciclu_ms - ciclu_ms) / 1000)
            elif not reusite:
                self._oprire.wait(PAUZA_FARA_REUSITA_S)

    # ------------------------------------------------------------ steaguri si conexiune
    def _steag(self, nume: str, detalii: str):
        with self._lock:
            self._steaguri_in_asteptare.append(nume)
            self.numar_steaguri[nume] += 1
        self.jurnal.scrie(f"Steag {nume}: {detalii}", "avertisment" if nume == "conexiune_pierduta" else "info")
        self._eveniment("steag", f"{nume}: {detalii}")

    def _stare_conexiune(self, reusite: int):
        if reusite:
            self._cicluri_fara_reusita = 0
            if self._conexiune_pierduta:
                self._conexiune_pierduta = False
                self._pas_reconectare = 0
                self.stare_text = self._text_ok
                self._steag("conexiune_restabilita", "citirile merg din nou")
            return
        self._cicluri_fara_reusita += 1
        if not self._conexiune_pierduta and self._cicluri_fara_reusita >= CICLURI_PANA_LA_PIERDERE:
            self._conexiune_pierduta = True
            self.stare_text = "reconectare"
            self._steag("conexiune_pierduta", f"{self._cicluri_fara_reusita} cicluri la rând fără nicio citire reușită")

    def _reconecteaza(self):
        """Asteapta (1 s, 2 s, 5 s, apoi la 5 s) si reporneste sesiunea de citire."""
        pauza = PAUZE_RECONECTARE[min(self._pas_reconectare, len(PAUZE_RECONECTARE) - 1)]
        self._pas_reconectare += 1
        if self._oprire.wait(pauza):
            return
        try:
            self.sursa.reset()
            self.jurnal.scrie(f"Reconectare: sesiunea de citire repornită (încercarea {self._pas_reconectare})")
        except Exception as e:  # noqa: BLE001
            self.jurnal.scrie(f"Reconectare eșuată (încercarea {self._pas_reconectare}): "
                              f"{explica(f'{type(e).__name__}: {e}')}", "eroare")

    def _citeste(self, c: profiles.Citire, rand: dict) -> int:
        # prima citire a jobului: FARA filtru, ca sa vina si unitatile (_EINH nu vin cu result_filter)
        cere_unitati = c.job not in self._unitati_cerute
        filtru = "" if cere_unitati else ";".join(c.valori.values())
        r = self.sursa.run(c.job, filtru, c.parametri, ecu=self.profil.ecu)
        s = self.statistici_joburi[c.job]
        s["n"] += 1
        s["ms_total"] += r.durata_ms
        if not r.ok:
            s["erori"] += 1
            self.erori += 1
            self._eroare_job(c.job, r)
            return 0
        s["ok"] += 1
        self._ultima_eroare.pop(c.job, None)
        v = r.valori()
        vu = {k.upper(): x for k, x in v.items()}
        for alias, rez in c.valori.items():
            if rez.upper() in vu:
                rand[alias] = vu[rez.upper()]
        if cere_unitati:
            self._unitati_cerute.add(c.job)
            for alias, rez in c.valori.items():
                u = vu.get(_nume_unitate(rez).upper())
                if u not in (None, ""):
                    self.mapare[alias]["unitate"] = str(u)
            self._scrie_coloane()
        return 1

    def _eroare_job(self, job: str, r):
        acum = self._ceas()
        prec = self._ultima_eroare.get(job)
        nivel = "avertisment" if r.avertisment else "eroare"
        if prec and prec[0] == r.eroare and acum - prec[1] < REPETARE_EROARE_S:
            self._ultima_eroare[job] = (prec[0], prec[1], prec[2] + 1)
            return
        repetari = f" (repetată de {prec[2]} ori)" if prec and prec[0] == r.eroare and prec[2] else ""
        text = f"{job}: {explica(r.eroare)}{repetari}"
        self.jurnal.scrie(text, nivel)
        self._eveniment("eroare", text)
        self._ultima_eroare[job] = (r.eroare, acum, 0)

    # ------------------------------------------------------------ erori si instantanee
    def _citeste_erori(self, eticheta: str):
        date, rezumat, ok = citeste_erori(self.sursa, self.profil.ecu)
        date["t_rel_s"] = round(self.t_rel(), 3)
        self.jurnal.scrie(f"Erori ({eticheta}): {rezumat}", "info" if ok else "eroare")
        _json(self.folder / f"erori_{eticheta}.json", date)
        self._eveniment("stare", f"erori citite ({eticheta}), ok={ok}")
        if not ok:
            return
        seturi = date["fs_lesen"]["seturi"]
        if self._erori_baza is not None:  # comparam cu ultima citire reusita
            for detalii in flags.compara_erori(self._erori_baza, seturi):
                self._steag("eroare_noua", detalii)
        self._erori_baza = seturi

    def _instantaneu(self):
        rez = {}
        for job in self.profil.instantaneu_la_start:
            r = self.sursa.run(job, ecu=self.profil.ecu)
            rez[job] = asdict(r)
            if not r.ok:
                self.jurnal.scrie(f"Instantaneu {job}: {explica(r.eroare)}", "avertisment" if r.avertisment else "eroare")
        _json(self.folder / "instantaneu_start.json", {"t_iso": _acum_iso(), "joburi": rez})
        ok = sum(1 for x in rez.values() if x["ok"])
        self.jurnal.scrie(f"Instantaneu la start: {ok}/{len(rez)} joburi reușite")

    # ------------------------------------------------------------ fisiere
    def _segment_nou(self):
        self._inchide_csv()
        self._segment += 1
        self._t_segment = self._ceas()
        cale = self.folder / f"date_{self._segment:03d}.csv"
        self._csv_fh = open(cale, "w", newline="", encoding="utf-8")
        self._csv = csv.DictWriter(self._csv_fh, fieldnames=self.coloane, extrasaction="ignore")
        self._csv.writeheader()
        self._csv_fh.flush()
        if self._segment > 1:
            self.jurnal.scrie(f"Segment nou: {cale.name}")
            self._eveniment("stare", f"segment nou {cale.name}")

    def _scrie_rand(self, rand: dict):
        if not self.scrie:  # live: doar in memorie (sub lock, ca date_live sa vada randuri intregi)
            with self._lock:
                self.buffer.append({**rand, "t_rel_s": float(rand["t_rel_s"]), "ciclu_ms": float(rand["ciclu_ms"])})
                self.randuri += 1
            return
        self._csv.writerow(rand)
        self._csv_fh.flush()
        acum = self._ceas()
        if acum - self._t_fsync >= 5:
            os.fsync(self._csv_fh.fileno())
            self._t_fsync = acum
        self.randuri += 1

    def _inchide_csv(self):
        if self._csv_fh:
            self._csv_fh.flush()
            os.fsync(self._csv_fh.fileno())
            self._csv_fh.close()
            self._csv_fh = self._csv = None

    def _eveniment(self, tip: str, detalii: str):
        with self._lock:
            self._nr_ev += 1
            self.evenimente_mem.append((self._nr_ev, round(self.t_rel(), 3), tip, detalii, _acum_iso()))
        if self._ev:
            self._ev.writerow([_acum_iso(), f"{self.t_rel():.3f}", tip, detalii])
            self._ev_fh.flush()

    def _scrie_coloane(self):
        if self.scrie:
            _json(self.folder / "coloane.json", self.mapare)

    def _scrie_sesiune(self, final: bool = False):
        _json(self.folder / "sesiune.json", {
            "versiune_aplicatie": __version__,
            "profil": self.profil.nume,
            "profil_toml": self.profil.sursa_toml,
            "conditie": self.conditie,
            "nota": self.nota,
            "sursa": type(self.sursa).__name__,
            "ecu": self.profil.ecu,
            "start": self._start_iso,
            "stop": _acum_iso() if final else None,
            "segmente": self._segment,
            "randuri": self.randuri,
            "motiv_oprire": self._motiv_oprire if final else None,
            "statistici": self.statistici(),
        })

    def _incheie(self):
        if not self.scrie:
            self.stare_text = "opreste"
            try:
                self.sursa.stop()
            except Exception:  # noqa: BLE001
                pass
            self._motiv_oprire = self._motiv_oprire or "oprit"
            self._t_final = self.t_rel()
            self.jurnal.scrie(f"Stop citire live ({self._motiv_oprire}). {self.randuri} rânduri citite, nimic salvat.")
            self.stare_text = "oprit"
            return
        if self.folder is None:
            return
        self.stare_text = "opreste"
        try:
            if self.profil.erori_la_stop and not self._rapid and getattr(self.sursa, "pornit", False) \
                    and not getattr(self.sursa, "epuizat", False):
                self._citeste_erori("stop")
        except Exception as e:  # noqa: BLE001
            self.jurnal.scrie(f"Citirea erorilor la stop a eșuat: {e}", "eroare")
        try:
            self.sursa.stop()
        except Exception:  # noqa: BLE001
            pass
        self._inchide_csv()
        self._motiv_oprire = self._motiv_oprire or "oprit"
        self._t_final = self.t_rel()
        st = self.statistici()
        self.jurnal.scrie(f"Stop ({self._motiv_oprire}). {self.randuri} rânduri în {st['durata_s']:.0f} s, "
                          f"{st['cicluri_pe_s']} cicluri/s")
        for job, s in st["joburi"].items():
            self.jurnal.scrie(f"  {job}: {s['n']} apeluri, {s['erori']} erori, medie {s['ms_medie']} ms")
        self._eveniment("stare", f"stop: {self._motiv_oprire}")
        self._scrie_sesiune(final=True)
        if self._ev_fh:
            self._ev_fh.close()
            self._ev_fh = self._ev = None
        self.jurnal.inchide_fisier()
        self.stare_text = "oprit"


# ---------------------------------------------------------------- consola

def creeaza_sursa(tip: str, ecu: str, replay: str | None = None, fake_tmot: float = 30.0):
    if tip == "fake":
        return FakeSource(ecu=ecu, tmot_start=fake_tmot)
    if tip == "ediabas":
        return EdiabasSource(ecu=ecu)
    if tip == "replay":
        if not replay:
            raise SystemExit("--sursa replay cere --replay <folder sesiune sau CSV>")
        return ReplaySource(replay, ecu=ecu, viteza=1)
    raise SystemExit(f"sursa necunoscută: {tip}")


def _taste():
    """Tasta apasata in consola (Windows) sau None."""
    try:
        import msvcrt
    except ImportError:
        return None
    if msvcrt.kbhit():
        return msvcrt.getwch()
    return None


def main(argv=None):
    for flux in (sys.stdout, sys.stderr):  # diacritice corecte in consola Windows
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser(description="Logger EDIABAS (doar citire) în consolă")
    ap.add_argument("--profil", required=True, help="nume din profiles/ sau cale .toml")
    ap.add_argument("--sursa", choices=("fake", "ediabas", "replay"), default="fake")
    ap.add_argument("--replay", help="folder de sesiune sau CSV pentru --sursa replay")
    ap.add_argument("--fake-tmot", type=float, default=30.0,
                    help="sursa fake: temperatura motorului la start (ex. 90 = motor cald)")
    ap.add_argument("--conditie", choices=CONDITII, default="necunoscut")
    ap.add_argument("--nota", default="")
    ap.add_argument("--durata", type=float, default=0, help="oprire automată după N secunde (0 = până la q/Ctrl+C)")
    ap.add_argument("--date", default=str(DIR_DATE), help="folderul de date")
    a = ap.parse_args(argv)

    try:
        profil = profiles.incarca(a.profil)
    except profiles.ProfilInvalid as e:
        print(e, file=sys.stderr)
        return 2
    blocare = sistem.BlocareInstanta(a.date)
    try:
        blocare.obtine(f"recorder {profil.nume}")
    except sistem.InstantaDejaPornita as e:
        print(e, file=sys.stderr)
        return 3
    atexit.register(blocare.elibereaza)
    sursa = creeaza_sursa(a.sursa, profil.ecu, a.replay, a.fake_tmot)
    jurnal = Jurnal(ecou=print)
    rec = Recorder(profil, sursa, dir_date=a.date, conditie=a.conditie, nota=a.nota, jurnal=jurnal)
    atexit.register(rec.opreste, "ieșire din program")
    sistem.ctrl_break_ca_ctrl_c()
    sistem.la_inchiderea_consolei(lambda: rec.opreste("fereastra de consolă închisă", rapid=True, timeout=4))
    if a.sursa == "ediabas":
        print("ATENȚIE: cât timp înregistrezi, nu folosi serverul MCP din chat.")
    taste = {m["tasta"]: m["eticheta"] for m in profil.marcaje if m["tasta"]}
    if taste:
        print("Marcaje: " + ", ".join(f"{k} = {v}" for k, v in sorted(taste.items())) + "; q = stop")
    rec.porneste()
    t_start, t_afis = time.monotonic(), 0.0
    try:
        while rec._fir.is_alive():
            k = _taste()
            if k in taste:
                rec.marcaj(taste[k])
            elif k in ("q", "Q", "\x1b"):
                rec.opreste()
                break
            if a.durata and time.monotonic() - t_start >= a.durata:
                rec.opreste(f"durata cerută în consolă ({a.durata:.0f} s)")
                break
            if time.monotonic() - t_afis >= 5 and rec.stare_text == "inregistreaza":
                t_afis = time.monotonic()
                s = rec.stare()
                rpm = s["valori"].get("rpm", {}).get("valoare")
                print(f"  [{s['timp_s']:.0f} s] rânduri {s['randuri']}, {s['cicluri_pe_s']} cicluri/s, "
                      f"erori {s['erori']}" + (f", rpm {rpm}" if rpm is not None else ""))
            time.sleep(0.05)
    except KeyboardInterrupt:
        rec.opreste("Ctrl+C")
    rec.opreste()
    return 0


if __name__ == "__main__":
    sys.exit(main())
