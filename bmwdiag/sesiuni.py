"""Citirea sesiunilor salvate (doar citire, fara EDIABAS): lista, detaliu, date pe coloane, rezumat.

Folosit de interfata web (rutele /api/sesiuni/...) si, mai tarziu, de rezumatul din consola.
Nu modifica niciodata fisierele unei sesiuni.
"""
import bisect
import csv
import json
import re
from datetime import datetime
from pathlib import Path

from .recorder import DIR_DATE

RE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[\w-]+$")
RE_FISIER = re.compile(r"^(sesiune\.json|coloane\.json|date_\d{3}\.csv|evenimente\.csv|erori_[\w-]+\.json|"
                       r"instantaneu_start\.json|jurnal\.txt)$")
COLOANE_FIXE = ("t_iso", "t_rel_s", "ciclu", "ciclu_ms", "marcaj", "steaguri")
CACHE_MAX = 3
_cache: dict = {}


class IdInvalid(ValueError):
    """Id de sesiune sau nume de fisier care nu respecta forma permisa (HTTP 400)."""


class NuExista(LookupError):
    """Sesiunea sau fisierul nu exista (HTTP 404)."""


def dir_sesiuni(dir_date=DIR_DATE) -> Path:
    return Path(dir_date) / "sesiuni"


def folder_sesiune(id_: str, dir_date=DIR_DATE) -> Path:
    if not isinstance(id_, str) or not RE_ID.fullmatch(id_):
        raise IdInvalid(f"Id de sesiune invalid: {id_!r}")
    baza = dir_sesiuni(dir_date).resolve()
    f = (baza / id_).resolve()
    if f.parent != baza:
        raise IdInvalid(f"Id de sesiune invalid: {id_!r}")
    if not f.is_dir():
        raise NuExista(f"Nu există sesiunea {id_}")
    return f


def _json(cale: Path):
    try:
        return json.loads(cale.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _numar(s):
    if s is None or s == "":
        return None
    try:
        # 5 cifre semnificative: scapa de zgomotul de virgula mobila (12.151800000000001), fisierul ramane neschimbat
        return float(f"{float(s):.5g}")
    except ValueError:
        return None


def _fisiere_date(f: Path) -> list[Path]:
    return sorted(f.glob("date_[0-9][0-9][0-9].csv"))


def _citeste_csv(cale: Path) -> tuple[list[str], list[list[str]]]:
    """Antet + randuri; ultimul rand trunchiat (mai putine celule decat antetul) se ignora."""
    with open(cale, newline="", encoding="utf-8", errors="replace") as fh:
        cititor = csv.reader(fh)
        antet = next(cititor, [])
        randuri = [r for r in cititor if len(r) == len(antet)]
    return antet, randuri


def _semnatura(f: Path) -> tuple:
    return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(f.iterdir()) if p.is_file())


class _Date:
    """Datele unei sesiuni, pe coloane: t (secunde) si cate o lista per coloana (None = celula goala)."""

    def __init__(self, antet: list[str], t: list[float], coloane: dict, text: dict):
        self.antet = antet
        self.t = t
        self.coloane = coloane
        self.text = text  # marcaj, steaguri, t_iso: liste de str


def _incarca_date(f: Path, activ: bool) -> _Date:
    cheie = str(f)
    sem = _semnatura(f)
    if not activ and cheie in _cache and _cache[cheie][0] == sem:
        return _cache[cheie][1]
    antet: list[str] = []
    t: list[float] = []
    coloane: dict[str, list] = {}
    text = {"t_iso": [], "marcaj": [], "steaguri": []}
    for cale in _fisiere_date(f):
        a, randuri = _citeste_csv(cale)
        if not antet:
            antet = a
            coloane = {c: [] for c in a if c not in COLOANE_FIXE or c in ("ciclu", "ciclu_ms")}
        idx = {c: i for i, c in enumerate(a)}
        if "t_rel_s" not in idx:
            continue
        for r in randuri:
            tv = _numar(r[idx["t_rel_s"]])
            if tv is None:
                continue
            t.append(tv)
            for c, lista in coloane.items():
                lista.append(_numar(r[idx[c]]) if c in idx else None)
            for c in text:
                text[c].append(r[idx[c]] if c in idx else "")
    rez = _Date(antet, t, coloane, text)
    if not activ:
        _cache[cheie] = (sem, rez)
        while len(_cache) > CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    return rez


def _evenimente(f: Path) -> list[dict]:
    cale = f / "evenimente.csv"
    if not cale.is_file():
        return []
    antet, randuri = _citeste_csv(cale)
    rez = []
    for r in randuri:
        d = dict(zip(antet, r))
        rez.append({"t_iso": d.get("t_iso", ""), "t_rel_s": _numar(d.get("t_rel_s")),
                    "tip": d.get("tip", ""), "detalii": d.get("detalii", "")})
    return rez


def _stare(f: Path, sesiune: dict | None, activ: bool) -> str:
    if activ:
        return "în desfășurare"
    if sesiune and sesiune.get("stop"):
        return "finalizată"
    return "întreruptă"


def _este_activ(f: Path, folder_activ) -> bool:
    return folder_activ is not None and Path(folder_activ).resolve() == f.resolve()


def _fa_rezumat_lista(f: Path, folder_activ) -> dict:
    id_ = f.name
    s = _json(f / "sesiune.json")
    activ = _este_activ(f, folder_activ)
    ev = None
    if s is None:
        s = {}
    st = s.get("statistici") or {}
    steaguri = dict(st.get("steaguri") or {})
    randuri = s.get("randuri")
    durata = st.get("durata_s")
    ciclu_s = st.get("cicluri_pe_s")
    start = s.get("start")
    if not s or not s.get("stop") or not steaguri:
        # sesiune neinchisa sau fara sesiune.json: reconstruim din fisiere
        ev = _evenimente(f)
        if not steaguri:
            for e in ev:
                if e["tip"] == "steag":
                    nume = e["detalii"].split(":", 1)[0].strip()
                    steaguri[nume] = steaguri.get(nume, 0) + 1
        d = _incarca_date(f, True)
        if d.t:
            randuri = len(d.t)
            neinchisa = not s.get("stop")  # sesiune.json are statistici zero pana la oprire: calculam din date
            if durata is None or (neinchisa and not durata):
                durata = d.t[-1] - d.t[0]
            if not start:
                start = d.text["t_iso"][0]
            if (ciclu_s is None or (neinchisa and not ciclu_s)) and d.t[-1] > d.t[0]:
                ciclu_s = round(len(d.t) / (d.t[-1] - d.t[0]), 3)
    if not start:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})", id_)
        start = f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}" if m else ""
    return {"id": id_, "start": start, "profil": s.get("profil") or id_.split("_", 2)[-1],
            "conditie": s.get("conditie") or "necunoscut", "durata_s": durata, "randuri": randuri,
            "cicluri_pe_s": ciclu_s, "steaguri": steaguri, "nota": s.get("nota") or "",
            "motiv_oprire": s.get("motiv_oprire"), "stare": _stare(f, s, activ)}


def lista(dir_date=DIR_DATE, folder_activ=None) -> list[dict]:
    """Sesiunile din bmw-data\\sesiuni, cea mai noua prima. Folderele care nu au forma de id se sar."""
    baza = dir_sesiuni(dir_date)
    if not baza.is_dir():
        return []
    rez = []
    for f in baza.iterdir():
        if f.is_dir() and RE_ID.fullmatch(f.name):
            try:
                rez.append(_fa_rezumat_lista(f, folder_activ))
            except Exception as e:  # noqa: BLE001 - o sesiune stricata nu strica lista
                rez.append({"id": f.name, "start": "", "profil": "?", "conditie": "necunoscut", "durata_s": None,
                            "randuri": None, "cicluri_pe_s": None, "steaguri": {}, "nota": "",
                            "motiv_oprire": None, "stare": "întreruptă", "eroare": str(e)})
    rez.sort(key=lambda s: s["id"], reverse=True)
    return rez


def rezumat(id_: str, dir_date=DIR_DATE, folder_activ=None) -> dict:
    """Min / medie / max pe fiecare coloana numerica, plus temperatura motorului la inceput si la sfarsit."""
    f = folder_sesiune(id_, dir_date)
    d = _incarca_date(f, _este_activ(f, folder_activ))
    mm = {}
    for c, vals in d.coloane.items():
        if c in ("ciclu",):
            continue
        v = [x for x in vals if x is not None]
        if v:
            mm[c] = {"min": min(v), "medie": sum(v) / len(v), "max": max(v), "n": len(v)}
    rez = {"randuri": len(d.t), "durata_s": (d.t[-1] - d.t[0]) if d.t else 0, "coloane": mm}
    if "tmot" in d.coloane:
        v = [x for x in d.coloane["tmot"] if x is not None]
        if v:
            rez["tmot_start"], rez["tmot_stop"] = v[0], v[-1]
    return rez


def _erori(f: Path) -> list[dict]:
    """Citirile de erori (start, intervale, stop), fara campurile tehnice; cele noi fata de start marcate."""
    def cheie(p: Path):
        n = p.stem.removeprefix("erori_")
        return (0, 0.0) if n == "start" else (2, 0.0) if n == "stop" else (1, _numar(n) or 0.0)
    rez, la_start = [], set()
    for p in sorted(f.glob("erori_*.json"), key=cheie):
        j = _json(p)
        if not isinstance(j, dict):
            continue
        seturi = ((j.get("fs_lesen") or {}).get("seturi")) or []
        detalii = j.get("detalii") or {}
        lista_e = []
        for s in seturi:
            if "F_ORT_NR" not in s:
                continue  # ultimul set e doar telegrama
            nr = s["F_ORT_NR"]
            lista_e.append({"nr": nr, "text": s.get("F_ORT_TEXT"), "simptom": s.get("F_SYMPTOM_TEXT"),
                            "stare": s.get("F_VORHANDEN_TEXT"), "hex": s.get("F_HEX_CODE"),
                            "detalii": _fara_tehnice((detalii.get(str(nr)) or {}).get("seturi") or [])})
        nume = p.stem.removeprefix("erori_")
        if nume == "start":
            la_start = {e["nr"] for e in lista_e}
        for e in lista_e:
            e["nou"] = nume != "start" and e["nr"] not in la_start
        rez.append({"fisier": p.name, "moment": nume, "t_iso": j.get("t_iso"), "t_rel_s": j.get("t_rel_s"),
                    "ok": (j.get("fs_lesen") or {}).get("ok"), "erori": lista_e})
    return rez


def _tehnic(cheie: str, val) -> bool:
    return cheie.startswith("_TEL") or cheie == "JOB_STATUS" or (isinstance(val, str) and val.startswith("hex:"))


def _fara_tehnice(seturi: list) -> list[dict]:
    return [{k: v for k, v in s.items() if not _tehnic(k, v)} for s in seturi if isinstance(s, dict)]


def _instantaneu(f: Path):
    j = _json(f / "instantaneu_start.json")
    if not isinstance(j, dict):
        return None
    joburi = {}
    for nume, r in (j.get("joburi") or {}).items():
        seturi = (r or {}).get("seturi") or []
        joburi[nume] = {"ok": (r or {}).get("ok"), "status": (r or {}).get("status"),
                        "seturi": [_fara_tehnice([s])[0] for s in seturi if isinstance(s, dict)]}
    return {"t_iso": j.get("t_iso"), "joburi": joburi}


def incarca(id_: str, dir_date=DIR_DATE, folder_activ=None) -> dict:
    f = folder_sesiune(id_, dir_date)
    s = _json(f / "sesiune.json") or {}
    s.pop("profil_toml", None)
    activ = _este_activ(f, folder_activ)
    return {"id": id_, "stare": _stare(f, s, activ), "sesiune": s, "coloane": _json(f / "coloane.json") or {},
            "rezumat": rezumat(id_, dir_date, folder_activ), "evenimente": _evenimente(f), "erori": _erori(f),
            "instantaneu": _instantaneu(f), "folder": str(f),
            "fisiere": [{"nume": p.name, "bytes": p.stat().st_size, "descarcabil": bool(RE_FISIER.fullmatch(p.name))}
                        for p in sorted(f.iterdir()) if p.is_file()]}


def _reduce(t: list, serii: dict, max_puncte: int):
    """Reducere min/max pe galeti: pastreaza extremele fiecarei serii (nu netezeste caderile scurte)."""
    n = len(t)
    if not max_puncte or n <= max_puncte:
        return t, serii
    galeti = max(1, max_puncte // 2)
    pas = n / galeti
    indici = set()
    for g in range(galeti):
        a, b = int(g * pas), min(n, int((g + 1) * pas))
        indici.add(a)
        for vals in serii.values():
            v = [(vals[i], i) for i in range(a, b) if vals[i] is not None]
            if v:
                indici.add(min(v)[1])
                indici.add(max(v)[1])
    ordine = sorted(indici)
    return [t[i] for i in ordine], {c: [vals[i] for i in ordine] for c, vals in serii.items()}


def date(id_: str, coloane: list[str], de_la: float | None = None, pana_la: float | None = None,
         max_puncte: int = 0, dir_date=DIR_DATE, folder_activ=None) -> dict:
    """{"t": [...], "<coloana>": [...]} cu None pentru celulele goale. Coloana necunoscuta -> IdInvalid."""
    f = folder_sesiune(id_, dir_date)
    d = _incarca_date(f, _este_activ(f, folder_activ))
    for c in coloane:
        if c not in d.coloane:
            raise IdInvalid(f"Coloană necunoscută: {c!r}")
    a = bisect.bisect_left(d.t, de_la) if de_la is not None else 0
    b = bisect.bisect_right(d.t, pana_la) if pana_la is not None else len(d.t)
    t = d.t[a:b]
    serii = {c: d.coloane[c][a:b] for c in coloane}
    t, serii = _reduce(t, serii, max_puncte)
    return {"t": t, **serii}


def rand(id_: str, t: float, dir_date=DIR_DATE, folder_activ=None) -> dict:
    """Randul cel mai apropiat de momentul t (secunde de la start)."""
    f = folder_sesiune(id_, dir_date)
    d = _incarca_date(f, _este_activ(f, folder_activ))
    if not d.t:
        raise NuExista("Sesiunea nu are rânduri.")
    i = bisect.bisect_left(d.t, t)
    if i > 0 and (i == len(d.t) or t - d.t[i - 1] <= d.t[i] - t):
        i -= 1
    r = {c: v[i] for c, v in d.coloane.items()}
    r.update(t_rel_s=d.t[i], t_iso=d.text["t_iso"][i], marcaj=d.text["marcaj"][i], steaguri=d.text["steaguri"][i])
    return r


def fisier(id_: str, nume: str, dir_date=DIR_DATE) -> Path:
    """Calea unui fisier din lista alba (pentru descarcare)."""
    f = folder_sesiune(id_, dir_date)
    if not isinstance(nume, str) or not RE_FISIER.fullmatch(nume):
        raise NuExista(f"Fișier nepermis: {nume!r}")
    p = f / nume
    if not p.is_file():
        raise NuExista(f"Nu există fișierul {nume}")
    return p


def jurnal(id_: str, dir_date=DIR_DATE) -> str:
    p = fisier(id_, "jurnal.txt", dir_date)
    return p.read_text(encoding="utf-8", errors="replace")
