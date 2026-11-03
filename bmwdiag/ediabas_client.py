"""Sesiune EDIABAS persistenta prin PyDIABAS (doar citire).

Spre deosebire de server.py (o sesiune per job), clientul tine O SINGURA
sesiune deschisa pe toata durata inregistrarii, pentru viteza. Trebuie rulat
cu Python pe 32 de biti (api32.dll este pe 32 de biti).
"""
import os
import threading
import time
from dataclasses import dataclass, field

from . import guard

EDIABAS_BIN = os.environ.get("EDIABAS_BIN", r"C:\EDIABAS\Bin")
ECU_IMPLICIT = "MEV9N46L"  # D_MOTOR rezolva la aceasta varianta; NU MSV70

_dll_pregatit = False


def pregateste_dll():
    """Pune C:\\EDIABAS\\Bin in PATH si in cautarea DLL-urilor (inainte de import pydiabas)."""
    global _dll_pregatit
    if _dll_pregatit:
        return
    if os.path.isdir(EDIABAS_BIN):
        os.environ["PATH"] = EDIABAS_BIN + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(EDIABAS_BIN)
    _dll_pregatit = True


def _printable(b: bytes):
    try:
        s = b.decode("ascii")
        if all(32 <= ord(c) < 127 or c in "\r\n\t" for c in s):
            return s
    except UnicodeDecodeError:
        pass
    return "hex:" + b.hex()


def decodeaza(v):
    """bytes -> text (sau 'hex:...'), recursiv in dict/list; restul ramane neschimbat."""
    if isinstance(v, (bytes, bytearray)):
        return _printable(bytes(v))
    if isinstance(v, dict):
        return {str(k): decodeaza(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [decodeaza(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


@dataclass
class RezultatJob:
    """Rezultatul unui job, comun pentru toate sursele (EDIABAS, fake, replay)."""
    job: str
    ecu: str
    ok: bool
    status: str | None = None          # JOB_STATUS ("OKAY" la succes; None daca jobul nu-l da, ex. TMODE)
    seturi: list[dict] = field(default_factory=list)  # seturile de date (fara setul de sistem)
    sistem: dict = field(default_factory=dict)        # setul 0: OBJECT, VARIANTE, JOBSTATUS...
    durata_ms: float = 0.0
    eroare: str | None = None          # text de eroare (comunicare sau JOB_STATUS)
    avertisment: bool = False          # esec de jurnalizat ca avertisment (ex. JOB_STATUS lipsa)

    def valori(self) -> dict:
        """Primul set de date (joburile STATUS_* au unul singur)."""
        return self.seturi[0] if self.seturi else {}


def status_job(seturi: list[dict]) -> str | None:
    """JOB_STATUS din seturile de date (de obicei in ultimul set)."""
    for s in reversed(seturi):
        if "JOB_STATUS" in s:
            return s["JOB_STATUS"]
    return None


def din_dicts(job: str, ecu: str, dicts: list[dict], durata_ms: float) -> RezultatJob:
    """Construieste RezultatJob din res.as_dicts() (element 0 = setul de sistem)."""
    dicts = decodeaza(dicts or [])
    sistem = dicts[0] if dicts else {}
    seturi = dicts[1:]
    status = status_job(seturi)
    if status is None:
        # TMODE nu da JOB_STATUS; pe ECU-ul real (verificat 01.11) apare mereu, si filtrat
        if ecu.upper() == "TMODE":
            return RezultatJob(job=job, ecu=ecu, ok=True, seturi=seturi, sistem=sistem, durata_ms=durata_ms)
        return RezultatJob(job=job, ecu=ecu, ok=False, seturi=seturi, sistem=sistem, durata_ms=durata_ms,
                           eroare="JOB_STATUS lipseste din raspuns", avertisment=True)
    ok = status == "OKAY"
    return RezultatJob(job=job, ecu=ecu, ok=ok, status=status, seturi=seturi, sistem=sistem,
                       durata_ms=durata_ms, eroare=None if ok else status)


class EdiabasClient:
    """Sesiune PyDIABAS persistenta. Thread-safe (un singur job odata)."""

    def __init__(self, ecu: str = ECU_IMPLICIT, fabrica=None):
        self.ecu = ecu
        self._fabrica = fabrica  # pentru teste: inlocuieste PyDIABAS
        self._p = None
        self._lock = threading.Lock()

    @property
    def pornit(self) -> bool:
        return self._p is not None

    def _creeaza(self):
        if self._fabrica is not None:
            return self._fabrica()
        pregateste_dll()
        from pydiabas import PyDIABAS
        return PyDIABAS()

    def start(self):
        with self._lock:
            if self._p is None:
                p = self._creeaza()
                p.start()
                self._p = p

    def stop(self):
        with self._lock:
            if self._p is not None:
                try:
                    self._p.end()
                finally:
                    self._p = None

    def reset(self):
        """end + start (dupa erori repetate de comunicare)."""
        with self._lock:
            if self._p is None:
                p = self._creeaza()
                p.start()
                self._p = p
            else:
                self._p.reset()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def run(self, job: str, filtru: str = "", parametri: str = "", ecu: str | None = None) -> RezultatJob:
        """Ruleaza un job de citire. Ridica guard.JobBlocat pentru joburi interzise.
        Erorile de comunicare (StateError etc.) NU se ridica: intorc ok=False cu textul erorii."""
        guard.verifica(job)
        ecu = ecu or self.ecu
        t0 = time.perf_counter()
        with self._lock:
            if self._p is None:
                return RezultatJob(job=job, ecu=ecu, ok=False, eroare="sesiunea EDIABAS nu este pornita")
            try:
                res = self._p.job(ecu, job, parametri, filtru)
                dicts = res.as_dicts()
            except Exception as e:  # noqa: BLE001
                return RezultatJob(job=job, ecu=ecu, ok=False, eroare=f"{type(e).__name__}: {e}",
                                   durata_ms=(time.perf_counter() - t0) * 1000)
        return din_dicts(job, ecu, dicts, (time.perf_counter() - t0) * 1000)
