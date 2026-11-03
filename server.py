"""Server MCP (doar citire) pentru EDIABAS, prin PyDIABAS.

Trebuie rulat cu Python pe 32 de biti (api32.dll este pe 32 de biti).
Scrierile (STEUERN_*, *_LOESCHEN, *_SCHREIBEN, flash etc.) sunt blocate.
"""
import logging
import os
import re
import sys
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# stdout este rezervat protocolului MCP, deci logam doar pe stderr
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("bmw-mcp")

EDIABAS_BIN = os.environ.get("EDIABAS_BIN", r"C:\EDIABAS\Bin")
ECU_DIR = Path(os.environ.get("EDIABAS_ECU", r"C:\EDIABAS\ECU"))

if os.path.isdir(EDIABAS_BIN):
    os.environ["PATH"] = EDIABAS_BIN + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(EDIABAS_BIN)

# Joburi permise: citiri si interogari ale descrierii SGBD-ului
ALLOWED = re.compile(r"^(STATUS_\w+|\w+_LESEN(_DETAIL)?|LESE_\w+|IDENT\w*|INFO|_\w+)$")
# Orice job cu aceste cuvinte este refuzat chiar daca trece de lista de mai sus
DENIED = re.compile(r"LOESCH|SCHREIB|STEUERN|FLASH|PROGRAM|RESET|CODIER.*(SCHREIB|LOESCH)|SET_|WRITE|ERASE|DELETE", re.I)

_lock = threading.Lock()  # EDIABAS accepta o singura sesiune simultan

mcp = FastMCP("bmw-ediabas")


def _printable(b: bytes):
    try:
        s = b.decode("ascii")
        if all(32 <= ord(c) < 127 or c in "\r\n\t" for c in s):
            return s
    except UnicodeDecodeError:
        pass
    return "hex:" + b.hex()


def _clean(v):
    if isinstance(v, (bytes, bytearray)):
        return _printable(bytes(v))
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _result_to_dict(result):
    out = {
        "ecu": getattr(result, "ecu", None),
        "job": getattr(result, "jobname", None),
        "jobstatus": getattr(result, "jobstatus", None),
    }
    try:
        out["sets"] = _clean(result.as_dicts())
    except Exception:
        try:
            out["sets"] = _clean([dict(s) for s in result.jobSets])
        except Exception:
            out["sets"] = str(result)
    return out


def _run(ecu: str, job: str, parameters: str = "", result_filter: str = "", check: bool = True):
    if check:
        if DENIED.search(job) or not ALLOWED.match(job):
            return {"error": f"Job '{job}' este blocat (server doar-citire)."}
    try:
        from pydiabas import PyDIABAS
    except Exception as e:  # noqa: BLE001
        return {"error": f"Nu pot importa pydiabas ({type(e).__name__}: {e}). "
                         "Verifica ca rulezi Python pe 32 de biti."}
    with _lock:
        try:
            with PyDIABAS() as p:
                res = p.job(ecu, job, parameters, result_filter)
                return _result_to_dict(res)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def ediabas_check() -> dict:
    """Verifica ca EDIABAS merge, fara masina: ruleaza ECU-ul simulat TMODE."""
    return {
        "ediabas_bin": EDIABAS_BIN,
        "ecu_dir": str(ECU_DIR),
        "python_bits": 8 * struct_size(),
        "tmode_test": _run("TMODE", "LESE_INTERFACE_TYP", check=False),
    }


def struct_size() -> int:
    import struct
    return struct.calcsize("P")


@mcp.tool()
def list_ecus(pattern: str = "") -> list[str]:
    """Listeaza SGBD-urile (.prg/.grp) din folderul ECU; filtru optional (ex: 'MSV', 'D_MOTOR')."""
    if not ECU_DIR.is_dir():
        return [f"Folderul {ECU_DIR} nu exista"]
    names = sorted({p.stem.upper() for p in ECU_DIR.iterdir()
                    if p.suffix.lower() in (".prg", ".grp")})
    if pattern:
        names = [n for n in names if pattern.upper() in n]
    return names[:300]


@mcp.tool()
def list_jobs(ecu: str) -> dict:
    """Listeaza joburile unui SGBD (nu comunica cu masina), ex: ecu='MSV70'."""
    return _run(ecu, "_JOBS")


@mcp.tool()
def describe_job(ecu: str, job: str) -> dict:
    """Descrie un job: comentariu, argumente si rezultate (nu comunica cu masina)."""
    return {
        "comment": _run(ecu, "_JOBCOMMENTS", job),
        "arguments": _run(ecu, "_ARGUMENTS", job),
        "results": _run(ecu, "_RESULTS", job),
    }


@mcp.tool()
def read_faults(ecu: str) -> dict:
    """Citeste memoria de erori (FS_LESEN). Necesita cablu conectat si contact pus."""
    return _run(ecu, "FS_LESEN")


@mcp.tool()
def run_job(ecu: str, job: str, parameters: str = "", result_filter: str = "") -> dict:
    """Ruleaza un job EDIABAS de citire. Parametrii separati prin ';'.
    Joburile de scriere/stergere/steuern sunt refuzate."""
    return _run(ecu, job, parameters, result_filter)


if __name__ == "__main__":
    mcp.run()
