"""Legatura cu Windows: o singura instanta, laptopul nu adoarme, inchiderea ferestrei de consola.

Pe alte sisteme functiile sunt fara efect (testele rulate pe Windows le acopera).
"""
import ctypes
import os
import signal
import threading
from pathlib import Path

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

# evenimente de consola dupa care Windows inchide procesul in ~5 s
CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 2, 5, 6


class InstantaDejaPornita(Exception):
    pass


class BlocareInstanta:
    """Fisier de blocare in folderul de date. Blocarea e tinuta de Windows pe fisierul deschis,
    deci dispare singura daca procesul moare (nu ramane blocare veche dupa o cadere)."""

    def __init__(self, folder):
        self.cale = Path(folder) / "logger.lock"
        self._fh = None

    def obtine(self, descriere: str = ""):
        self.cale.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.cale, "a+", encoding="utf-8")
        try:
            _blocheaza(fh)
        except OSError:
            fh.seek(0)
            cine = fh.read().strip() or "alt proces"
            fh.close()
            raise InstantaDejaPornita(
                f"Loggerul rulează deja ({cine}). Închide-l mai întâi; fișier de blocare: {self.cale}") from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"PID {os.getpid()} {descriere}".strip())
        fh.flush()
        self._fh = fh
        return self

    def elibereaza(self):
        if self._fh:
            try:
                _deblocheaza(self._fh)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self):
        return self.obtine()

    def __exit__(self, *exc):
        self.elibereaza()


# Pe Windows blocarea e obligatorie: un octet blocat nu mai poate fi citit nici de alt proces.
# Blocam un octet departe de text, ca a doua instanta sa poata citi cine tine blocarea.
_OCTET_BLOCARE = 1 << 20


def _blocheaza(fh):
    fh.seek(_OCTET_BLOCARE)
    try:
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except ImportError:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _deblocheaza(fh):
    fh.seek(_OCTET_BLOCARE)
    try:
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except ImportError:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _kernel32():
    return getattr(ctypes, "windll", None) and ctypes.windll.kernel32


def impiedica_adormirea() -> bool:
    """Laptopul nu intra in somn cat ruleaza firul apelant (starea e per fir).
    Ecranul se poate stinge; capacul inchis poate totusi adormi laptopul (setare Windows)."""
    k = _kernel32()
    if not k:
        return False
    k.SetThreadExecutionState.restype = ctypes.c_uint32
    return k.SetThreadExecutionState(ctypes.c_uint32(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)) != 0


def permite_adormirea() -> bool:
    k = _kernel32()
    if not k:
        return False
    k.SetThreadExecutionState.restype = ctypes.c_uint32
    return k.SetThreadExecutionState(ctypes.c_uint32(ES_CONTINUOUS)) != 0


_handler_consola = None  # tinut in viata: Windows il apeleaza din alt fir


def la_inchiderea_consolei(functie) -> bool:
    """`functie()` ruleaza cand fereastra de consola e inchisa (sau la logoff/oprire Windows).
    Windows lasa ~5 s; functia trebuie sa fie rapida (inchide fisierele, scrie sesiune.json)."""
    global _handler_consola
    k = _kernel32()
    if not k:
        return False
    tip = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint32)

    def handler(eveniment):
        if eveniment in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            try:
                functie()
            except Exception:  # noqa: BLE001
                pass
            return 1
        return 0  # Ctrl+C / Ctrl+Break: tratarea obisnuita din Python

    _handler_consola = tip(handler)
    return bool(k.SetConsoleCtrlHandler(_handler_consola, 1))


def ctrl_break_ca_ctrl_c():
    """Ctrl+Break (si semnalul trimis de teste) -> KeyboardInterrupt, ca Ctrl+C: oprire curata."""
    if hasattr(signal, "SIGBREAK") and threading.current_thread() is threading.main_thread():
        def _intrerupe(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, _intrerupe)
