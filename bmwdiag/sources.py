"""Surse de date cu aceeasi interfata ca EdiabasClient.

Toate au: start(), stop(), reset(), ciclu_nou(), run(job, filtru, parametri, ecu) -> RezultatJob.
- EdiabasSource: masina reala (sesiune EDIABAS persistenta).
- FakeSource: valori sintetice plauzibile (incalzire, caderi de turatie la cuplare).
- ReplaySource: reda un CSV inregistrat, rand cu rand (un rand pe ciclu).
Garda doar-citire se aplica la fiecare apel, in toate sursele.
"""
import csv
import json
import math
import random
import threading
import time
from pathlib import Path

from . import guard
from .ediabas_client import ECU_IMPLICIT, EdiabasClient, RezultatJob


def _filtreaza(valori: dict, filtru: str) -> dict:
    """Aplica result_filter ca EDIABAS: doar numele cerute (fara diferenta de majuscule)."""
    if not filtru:
        return valori
    cerute = {n.strip().upper() for n in filtru.split(";") if n.strip()}
    return {k: v for k, v in valori.items() if k.upper() in cerute}


def _nume_unitate(rezultat: str) -> str:
    return rezultat[:-5] + "_EINH" if rezultat.upper().endswith("_WERT") else rezultat + "_EINH"


class EdiabasSource(EdiabasClient):
    """Masina reala. ciclu_nou() nu face nimic."""

    def ciclu_nou(self):
        pass


# ---------------------------------------------------------------- FakeSource

class FakeSource:
    """Motor simulat: se incalzeste de la tmot_start spre 90 C; la fiecare
    `perioada_cuplare_s` (sau la cupleaza()) turatia cade, mai mult la cald
    (simptomul investigat). Determinist pentru acelasi `seed` si acelasi ceas."""

    DURATA_CUPLARE_S = 2.0

    def __init__(self, ecu: str = ECU_IMPLICIT, seed: int = 1, tmot_start: float = 30.0,
                 tau_incalzire_s: float = 480.0, perioada_cuplare_s: float = 20.0,
                 latenta_ms: float = 80.0, rata_eroare: float = 0.0, ceas=time.monotonic):
        self.ecu = ecu
        self.tmot_start = tmot_start
        self.tau = tau_incalzire_s
        self.perioada_cuplare_s = perioada_cuplare_s  # 0 = doar manual
        self.latenta_ms = latenta_ms                  # timp simulat pe job (K-line e lenta)
        self.rata_eroare = rata_eroare                # probabilitatea ca un job sa esueze
        self.deconectat = False                       # simuleaza cablul scos
        self._ceas = ceas
        self._rnd = random.Random(seed)
        self._lock = threading.Lock()
        self._t0 = None
        self._cuplare_manuala = None
        self.erori = []
        self.adauga_eroare(11107, "CDKPH2 - Nockenwellengeber Auslass (simulat)", 0, "Fehler bisher nicht aufgetreten")

    # --- sesiune
    @property
    def pornit(self) -> bool:
        return self._t0 is not None

    def start(self):
        if self._t0 is None:
            self._t0 = self._ceas()

    def stop(self):
        self._t0 = None

    def reset(self):
        if self._t0 is None:
            self.start()

    def ciclu_nou(self):
        pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def cupleaza(self):
        """Porneste acum o cuplare de ambreiaj simulata."""
        self._cuplare_manuala = self._ceas()

    # --- modelul
    def _t(self) -> float:
        return self._ceas() - self._t0

    def _faza_cuplare(self, t: float) -> float | None:
        """Secunde de la inceputul cuplarii curente, sau None daca nu e cuplare."""
        candidati = []
        if self.perioada_cuplare_s > 0 and t >= self.perioada_cuplare_s:
            candidati.append(t % self.perioada_cuplare_s)
        if self._cuplare_manuala is not None:
            candidati.append(self._ceas() - self._cuplare_manuala)
        active = [c for c in candidati if 0 <= c < self.DURATA_CUPLARE_S]
        return min(active) if active else None

    def stare(self) -> dict:
        """Marimile fizice simulate in acest moment (fara zgomot)."""
        t = self._t()
        tmot = 90 - (90 - self.tmot_start) * math.exp(-t / self.tau)
        cald = min(max((tmot - 30) / 60, 0.0), 1.0)          # 0 = rece, 1 = cald
        rpm_tinta = 1100 - 400 * cald
        rpm, sarcina, pedala, viteza = rpm_tinta, 15.0 + 8 * (1 - cald), 0.0, 0.0
        faza = self._faza_cuplare(t)
        if faza is not None:
            adancime = 110 + 160 * cald                     # la cald cade mai mult
            if faza < 0.5:
                k = faza / 0.5
            else:
                k = max(0.0, 1 - (faza - 0.5) / 1.5)
            rpm -= adancime * k
            sarcina += 25 * k
            viteza = 4 * faza
        return {
            "t": t, "tmot": tmot, "cald": cald, "rpm": rpm, "rpm_tinta": rpm_tinta,
            "sarcina": sarcina, "pedala": pedala, "viteza": viteza,
            "maf": 5.5 + 17 * (1 - cald) + 0.4 * (sarcina - 15), "cuplare": faza is not None,
        }

    def _z(self, sigma: float) -> float:
        return self._rnd.gauss(0, sigma)

    def _valori_job(self, job: str, parametri: str):
        """dict cu rezultatele jobului (nume EDIABAS), sau None daca jobul nu e simulat."""
        s = self.stare()
        z = self._z
        w = lambda nume, val, unit: {f"STAT_{nume}_WERT": round(val, 3), f"STAT_{nume}_EINH": unit}  # noqa: E731
        if job == "STATUS_MESSWERTE":
            r = {}
            for d in (w("NMOT", s["rpm"] + z(4), "1/min"), w("NSOL", s["rpm_tinta"], "1/min"),
                      w("TMOT", s["tmot"], "Grad C"), w("TANS", 25 + 12 * s["cald"] + z(0.2), "Grad C"),
                      w("TKA", 20.25, "Grad C"), w("UB", 14.1 + z(0.03), "V"),
                      w("VFZG", s["viteza"], "km/h"), w("UPWG", 0.718 + z(0.002), "V"),
                      w("MSHFM", s["maf"] + z(0.2), "kg/h"), w("MIIST", 9.2 + 0.5 * (s["sarcina"] - 15), "%"),
                      w("FR", 1 - 0.013 * s["cald"] + z(0.005), ""), w("FR2", 1 + 0.005 * s["cald"] + z(0.005), ""),
                      w("TE", 2.2 + 0.04 * s["sarcina"] + z(0.02), "ms"), w("WDKBA", 2.75 + 0.1 * (s["sarcina"] - 15), "%DK"),
                      w("ZWOUT", 12 + z(0.5), "Grad KW"), w("WNWKWA", 600.8 + z(0.3), "Grad KW"),
                      w("WNWKWE", 620.2 + z(0.3), "Grad KW"),
                      w("RKRN0", 3.59, "V"), w("RKRN1", 3.75, "V"), w("RKRN2", 3.05, "V"), w("RKRN3", 7.03, "V")):
                r.update(d)
            return r
        if job == "STATUS_FASTA2":
            r = {}
            for d in (w("RL", s["sarcina"] + z(0.2), "%"), w("RLSOL", s["sarcina"] + 0.4, "%"),
                      w("WPED", s["pedala"], "%PED"), w("WDKS", 3.05, "%"), w("MIMIN", 10.6, "%"),
                      w("ZWIST", 15 + z(0.5), "Grad KW"), w("TE", 2.856 + z(0.02), "ms"),
                      w("TE2", 2.336 + z(0.02), "ms"), w("DMLLRI", -1.05 + z(0.1), "%"),
                      w("NSOLFASTA", s["rpm_tinta"], "1/min"), w("VVTSTATUS", 255, ""),
                      w("WDKBAFASTA", 3.03, "%")):
                r.update(d)
            r["STAT_MIL_EIN"] = 0
            return r
        if job == "STATUS_LAUFUNRUHE":
            r = {}
            for i, m in enumerate((-2.3, 1.2, 1.0, 0.1), start=1):
                r.update(w(f"LUTSFI{i}", m + z(0.15), "1/s"))
            r.update(w("UULSUV", 0.45 + z(0.05), "V"))
            r.update(w("UULSUV2", 0.45 + z(0.05), "V"))
            r["STAT_FOFR1_EIN"] = 0
            return r
        if job == "STATUS_FUNKTIONSSTATI":
            bucla = 1 if s["tmot"] > 45 else 0
            return {"STAT_LL_EIN": 0 if s["cuplare"] else 1, "STAT_LR_EIN": bucla, "STAT_LR2_EIN": bucla,
                    "STAT_LRNRDY_EIN": 1, "STAT_KD_EIN": 0, "STAT_PN_EIN": 0, "STAT_SA_EIN": 0,
                    "STAT_VL_EIN": 0, "STAT_ECULOCK_EIN": 0}
        sonde = {"STATUS_L_SONDE": ("L_SONDE", 1.5), "STATUS_L_SONDE_2": ("L_SONDE_2", 1.5),
                 "STATUS_L_SONDE_H": ("L_SONDE_H", 0.12), "STATUS_L_SONDE_2_H": ("L_SONDE_2_H", 0.68)}
        if job in sonde:
            nume, val = sonde[job]
            return w(nume, val + z(0.02), "V")
        if job == "STATUS_GEMISCH":
            r = {}
            for nume, val in (("FRA", 1.02), ("FRA2", 0.984), ("RKAT", 0.0), ("RKAT2", 0.0),
                              ("TEDUB", 0.0), ("TEDUB2", 0.0)):
                r.update(w(nume, val, ""))
            return r
        if job == "STATUS_VVT":
            r = {}
            for nume, val in (("VVTIW", 0.6), ("VVTSW", 0.6), ("VVTIW2", 7.4), ("VVTSW2", 4.5)):
                r.update(w(nume, val + z(0.01), "mm"))
            return r
        if job == "STATUS_GEBERRAD_ADAPTION":
            return {"STAT_VSA_WERT": 0.0, "STAT_VSE_WERT": 0.0, "STAT_VSA_2_WERT": 0.0, "STAT_VSE_2_WERT": 6553.5}
        if job == "STATUS_MOTORDREHZAHL":
            return w("MOTORDREHZAHL", s["rpm"] + z(4), "1/min")
        if job == "STATUS_MOTORTEMPERATUR":
            return w("MOTORTEMPERATUR", s["tmot"], "Grad C")
        if job == "STATUS_UBATT":
            return w("UBATT", 14.1 + z(0.03), "V")
        if job == "STATUS_READINESS":
            return {"STAT_KAT_EIN": 0, "STAT_LAMBDA_EIN": 1}
        if job == "STATUS_FASTA1":
            r = {}
            for nume, val, unit in (("DPS", 47.7, "hPa"), ("TSG", 25 + 15 * s["cald"], "Grad C")):
                r.update(w(nume, val + z(0.1), unit))
            return r
        if job == "STATUS_AN_LUFTTEMPERATUR":
            return w("AN_LUFTTEMPERATUR", 25 + 12 * s["cald"], "Grad C")
        if job == "STATUS_LMM_MASSE":
            return w("LMM_MASSE", s["maf"] + z(0.2), "kg/h")
        if job == "STATUS_PWG_POTI_SPANNUNG":
            return {**w("PWG_POTI_SPANNUNG_1", 0.718, "V"), **w("PWG_POTI_SPANNUNG_2", 0.36, "V")}
        if job in ("STATUS_LLABG", "STATUS_DKHFM", "STATUS_SAUGROHR"):
            return w(job[7:], 0.0, "")
        if job in ("STATUS_SYSTEMCHECK_KAT", "STATUS_SYSTEMCHECK_LAMBDA_AUS"):
            return {"STAT_SYSTEMCHECK_TEXT": "Steuerbetrieb durch Betriebsbedingungen (simulat)"}
        if job == "IDENT":
            return {"ID_BMW_NR": "7565300", "ID_HW_NR": "01", "ID_SW_NR": "0.16.89",
                    "ID_DATUM": "10.01.2005", "VARIANTE": "MEV9N46L (simulat)"}
        if job in ("ZIF_LESEN", "DATEN_REFERENZ_LESEN", "HARDWARE_REFERENZ_LESEN"):
            return {"ZIF_PROGRAMM_STAND": "0087360T410B", "DATEN_REFERENZ": "0SIYG", "SIMULAT": "da"}
        return None

    def adauga_eroare(self, nr: int, text: str, vorhanden_nr: int = 1,
                      vorhanden_text: str = "Fehler momentan vorhanden"):
        """Simuleaza aparitia (sau schimbarea starii) unei erori in memoria DME."""
        self.erori = [e for e in self.erori if e["nr"] != nr]
        self.erori.append({"nr": nr, "text": text, "vorhanden_nr": vorhanden_nr, "vorhanden_text": vorhanden_text})

    def _set_eroare(self, e: dict) -> dict:
        # formatul observat pe MEV9N46L (01.11.2026)
        return {"F_VERSION": 2, "F_ORT_NR": e["nr"], "F_ORT_TEXT": e["text"],
                "F_HEX_CODE": f"hex:{e['nr']:04x}88", "F_SYMPTOM_NR": 8,
                "F_SYMPTOM_TEXT": "unplausible Phasenflankenanzahl",
                "F_VORHANDEN_NR": e["vorhanden_nr"], "F_VORHANDEN_TEXT": e["vorhanden_text"],
                "F_WARNUNG_NR": 0, "F_WARNUNG_TEXT": "nein", "F_READY_NR": 0, "F_READY_TEXT": "ja"}

    def _seturi_erori(self, job: str, parametri: str):
        if job == "FS_LESEN":
            return [self._set_eroare(e) for e in self.erori] + [{"JOB_STATUS": "OKAY"}]
        if job == "FS_LESEN_DETAIL":
            e = next((x for x in self.erori if str(x["nr"]) == parametri.strip()), None)
            if e is None:
                return [{"JOB_STATUS": "ERROR_F_CODE", "JOB_MESSAGE": "Fehlerort nicht vorhanden"}]
            detaliu = {**self._set_eroare(e), "F_UW_KM": 253576, "F_UW_ANZ": 4,
                       "F_UW1_NR": 1, "F_UW1_TEXT": "Drehzahl", "F_UW1_WERT": 780.0, "F_UW1_EINH": "1/min",
                       "F_UW2_NR": 2, "F_UW2_TEXT": "Motortemperatur", "F_UW2_WERT": 77.25, "F_UW2_EINH": "Grad C",
                       "F_ART_ANZ": 1, "F_ART1_NR": 8, "F_ART1_TEXT": "unplausible Phasenflankenanzahl",
                       "F_LZ": 40, "F_HFK": 1, "F_PCODE": 0x0365, "F_PCODE_STRING": "P0365",
                       "F_PCODE_TEXT": "Camshaft Position Sensor B (simulat)"}
            al_doilea = {"F_UW_KM": 253580, "F_UW1_WERT": 820.0, "F_UW2_WERT": 78.0}
            return [detaliu, al_doilea, {"JOB_STATUS": "OKAY", "JOB_MESSAGE": "Fehlerspeicher gelesen"}]
        return None

    def run(self, job: str, filtru: str = "", parametri: str = "", ecu: str | None = None) -> RezultatJob:
        guard.verifica(job)
        ecu = ecu or self.ecu
        t0 = time.perf_counter()
        if self.latenta_ms > 0:
            time.sleep(self.latenta_ms / 1000)
        with self._lock:
            def gata(**kw):
                return RezultatJob(job=job, ecu=ecu, durata_ms=(time.perf_counter() - t0) * 1000, **kw)

            if self._t0 is None:
                return gata(ok=False, eroare="sesiunea (simulata) nu este pornita")
            if self.deconectat:
                return gata(ok=False, eroare="StateError: IFH-0018: INITIALIZATION ERROR (simulat)")
            if self.rata_eroare > 0 and self._rnd.random() < self.rata_eroare:
                return gata(ok=False, eroare="StateError: IFH-0009: NO RESPONSE FROM CONTROLUNIT (simulat)")
            sistem = {"OBJECT": ecu.lower(), "JOBNAME": job, "VARIANTE": ecu, "JOBSTATUS": ""}
            seturi = self._seturi_erori(job, parametri)
            if seturi is None:
                valori = self._valori_job(job, parametri)
                if valori is None:
                    status = "ERROR_ECU_SERVICE_NOT_SUPPORTED"
                    return gata(ok=False, status=status, eroare=status + " (job nesimulat)",
                                seturi=[{"JOB_STATUS": status}], sistem=sistem)
                seturi = [{**valori, "JOB_STATUS": "OKAY"}]
            status = next((x["JOB_STATUS"] for x in reversed(seturi) if "JOB_STATUS" in x), None)
            seturi = [_filtreaza(x, filtru) for x in seturi]
            ok = status == "OKAY"
            return gata(ok=ok, status=status, seturi=seturi, sistem=sistem, eroare=None if ok else status)


# -------------------------------------------------------------- ReplaySource

def _numar(text: str):
    try:
        return float(text)
    except ValueError:
        return text


class ReplaySource:
    """Reda un CSV inregistrat: fiecare ciclu_nou() trece la randul urmator.

    `cale`: un fisier CSV sau folderul unei sesiuni (citeste date_*.csv in ordine).
    `coloane`: {alias: {"job": ..., "rezultat": ..., "unitate": ...}}; daca lipseste,
    se citeste coloane.json de langa CSV. Coloanele fara mapare sunt ignorate.
    `viteza`: 0 = cat de repede se poate; 1 = timp real (dupa t_rel_s); 2 = de doua ori mai repede.
    """

    def __init__(self, cale, coloane: dict | None = None, ecu: str = ECU_IMPLICIT, viteza: float = 0.0,
                 latenta_ms: float = 0.0):
        cale = Path(cale)
        fisiere = sorted(cale.glob("date_*.csv")) if cale.is_dir() else [cale]
        if not fisiere or not all(f.is_file() for f in fisiere):
            raise FileNotFoundError(f"Nu gasesc date CSV in {cale}")
        if coloane is None:
            cj = (cale if cale.is_dir() else cale.parent) / "coloane.json"
            if not cj.is_file():
                raise FileNotFoundError(f"Lipseste coloane.json langa {cale}; da maparea prin `coloane`.")
            coloane = json.loads(cj.read_text(encoding="utf-8"))
        self.ecu = ecu
        self.viteza = viteza
        self.latenta_ms = latenta_ms
        self.randuri: list[dict] = []
        for f in fisiere:
            with open(f, newline="", encoding="utf-8") as fh:
                self.randuri.extend(csv.DictReader(fh))
        # job -> [(alias, rezultat, unitate)]
        self._pe_job: dict[str, list[tuple[str, str, str]]] = {}
        for alias, c in coloane.items():
            guard.verifica(c["job"])
            self._pe_job.setdefault(c["job"], []).append((alias, c["rezultat"], c.get("unitate", "")))
        self._idx = -1
        self._pornit = False
        self._ultim_ceas = None
        self._ultim_t_rel = None

    @property
    def pornit(self) -> bool:
        return self._pornit

    @property
    def index(self) -> int:
        return max(self._idx, 0)

    @property
    def epuizat(self) -> bool:
        return self._idx >= len(self.randuri)

    def start(self):
        self._pornit = True

    def stop(self):
        self._pornit = False

    def reset(self):
        self._pornit = True

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def ciclu_nou(self):
        """Trece la randul urmator; la viteza > 0 asteapta dupa t_rel_s."""
        self._idx += 1
        if self.viteza > 0 and not self.epuizat:
            t_rel = self.randuri[self._idx].get("t_rel_s")
            try:
                t_rel = float(t_rel)
            except (TypeError, ValueError):
                t_rel = None
            if t_rel is not None and self._ultim_t_rel is not None:
                tinta = self._ultim_ceas + (t_rel - self._ultim_t_rel) / self.viteza
                pauza = tinta - time.monotonic()
                if pauza > 0:
                    time.sleep(pauza)
            if t_rel is not None:
                self._ultim_t_rel, self._ultim_ceas = t_rel, time.monotonic()

    def run(self, job: str, filtru: str = "", parametri: str = "", ecu: str | None = None) -> RezultatJob:
        guard.verifica(job)
        ecu = ecu or self.ecu
        if self.latenta_ms > 0:
            time.sleep(self.latenta_ms / 1000)

        def gata(**kw):
            return RezultatJob(job=job, ecu=ecu, **kw)

        if not self._pornit:
            return gata(ok=False, eroare="sesiunea (replay) nu este pornita")
        if self.epuizat:
            return gata(ok=False, eroare="sfarsitul inregistrarii (replay)")
        if job not in self._pe_job:
            return gata(ok=False, eroare=f"jobul {job} nu exista in inregistrare (replay)")
        rand = self.randuri[self.index]
        valori = {}
        for alias, rezultat, unitate in self._pe_job[job]:
            text = (rand.get(alias) or "").strip()
            if text:  # celula goala = grupul nu a fost citit in acel ciclu
                valori[rezultat] = _numar(text)
                valori[_nume_unitate(rezultat)] = unitate
        valori["JOB_STATUS"] = "OKAY"
        return gata(ok=True, status="OKAY", seturi=[_filtreaza(valori, filtru)],
                    sistem={"OBJECT": "replay", "JOBNAME": job, "VARIANTE": ecu, "JOBSTATUS": ""})
