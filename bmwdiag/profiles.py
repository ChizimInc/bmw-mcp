"""Profile de inregistrare (TOML): incarcare si validare stricta.

Un profil invalid (camp lipsa, job refuzat de garda, alias duplicat) nu se
incarca: se ridica ProfilInvalid cu TOATE problemele gasite, in romana.
"""
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import flags, guard

DIR_PROFILE = Path(__file__).resolve().parents[1] / "profiles"

# coloane fixe din CSV: un alias nu poate avea aceste nume
COLOANE_FIXE = ("t_iso", "t_rel_s", "ciclu", "ciclu_ms", "marcaj", "steaguri")
_ALIAS = re.compile(r"^[a-z][a-z0-9_]*$")
_REZULTAT = re.compile(r"^\w+$")
CHEI_PROFIL = {"nume", "descriere", "ecu", "segment_minute", "durata_max_minute", "cicluri_max", "min_ciclu_ms",
               "erori_la_start",
               "erori_la_stop", "erori_interval_minute", "instantaneu_la_start", "grup", "marcaj", "steag"}
CHEI_GRUP = {"nume", "la_fiecare_s", "citire"}
CHEI_CITIRE = {"job", "valori", "parametri"}
CHEI_MARCAJ = {"eticheta", "tasta"}


class ProfilInvalid(Exception):
    pass


@dataclass
class Citire:
    job: str
    valori: dict[str, str]          # alias -> rezultat EDIABAS
    parametri: str = ""


@dataclass
class Grup:
    nume: str
    la_fiecare_s: float             # 0 = in fiecare ciclu
    citiri: list[Citire]


@dataclass
class Profil:
    nume: str
    descriere: str
    ecu: str
    grupuri: list[Grup]
    segment_minute: float = 0
    durata_max_minute: float = 0
    cicluri_max: int = 0            # 0 = fara limita; 1 = o singura trecere (instantaneu_complet)
    min_ciclu_ms: float = 0
    erori_la_start: bool = True
    erori_la_stop: bool = True
    erori_interval_minute: float = 0
    instantaneu_la_start: list[str] = field(default_factory=list)
    marcaje: list[dict] = field(default_factory=list)   # {eticheta, tasta}
    steaguri: list[dict] = field(default_factory=list)  # evaluate in etapa 3
    sursa_toml: str = ""

    def aliasuri(self) -> list[str]:
        return [a for g in self.grupuri for c in g.citiri for a in c.valori]

    def toate_joburile(self) -> list[str]:
        joburi = [c.job for g in self.grupuri for c in g.citiri] + list(self.instantaneu_la_start)
        if self.erori_la_start or self.erori_la_stop or self.erori_interval_minute:
            joburi += ["FS_LESEN", "FS_LESEN_DETAIL"]
        return joburi


def _numar(d: dict, cheie: str, implicit, probleme: list, unde: str):
    v = d.get(cheie, implicit)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        probleme.append(f"{unde}: '{cheie}' trebuie să fie un număr ≥ 0 (este {v!r})")
        return implicit
    return v


def din_dict(d: dict, sursa_toml: str = "") -> Profil:
    p: list[str] = []  # probleme

    def chei(dd, permise, unde):
        for k in sorted(set(dd) - permise):
            p.append(f"{unde}: cheie necunoscută '{k}' (greșeală de scriere?)")

    def text(dd, cheie, unde, obligatoriu=True, implicit=""):
        v = dd.get(cheie, implicit)
        if not isinstance(v, str) or (obligatoriu and not v.strip()):
            p.append(f"{unde}: lipsește '{cheie}' (text)")
            return implicit
        return v

    chei(d, CHEI_PROFIL, "profil")
    nume = text(d, "nume", "profil")
    ecu = text(d, "ecu", "profil")
    if ecu.upper().startswith("MSV70"):
        p.append("profil: ecu 'MSV70' e varianta greșită pentru această mașină; folosește 'MEV9N46L'")

    grupuri, vazute = [], set()
    lista_grupuri = d.get("grup", [])
    if not isinstance(lista_grupuri, list) or not lista_grupuri:
        p.append("profil: trebuie cel puțin un [[grup]]")
        lista_grupuri = []
    for i, g in enumerate(lista_grupuri, start=1):
        ug = f"grupul {i} ({g.get('nume', '?')})"
        chei(g, CHEI_GRUP, ug)
        citiri = []
        lista_citiri = g.get("citire", [])
        if not isinstance(lista_citiri, list) or not lista_citiri:
            p.append(f"{ug}: trebuie cel puțin un [[grup.citire]]")
            lista_citiri = []
        for j, c in enumerate(lista_citiri, start=1):
            uc = f"{ug}, citirea {j}"
            chei(c, CHEI_CITIRE, uc)
            job = text(c, "job", uc)
            if job and (motiv := guard.motiv_refuz(job)):
                p.append(f"{uc}: {motiv} (doar citire)")
            valori = c.get("valori")
            if not isinstance(valori, dict) or not valori:
                p.append(f"{uc}: lipsește 'valori' (alias = \"REZULTAT\")")
                valori = {}
            for alias, rez in valori.items():
                if not _ALIAS.match(alias):
                    p.append(f"{uc}: aliasul '{alias}' trebuie să fie litere mici, cifre și '_'")
                elif alias in COLOANE_FIXE:
                    p.append(f"{uc}: aliasul '{alias}' e rezervat")
                elif alias in vazute:
                    p.append(f"{uc}: aliasul '{alias}' e folosit de două ori")
                vazute.add(alias)
                if not isinstance(rez, str) or not _REZULTAT.match(rez):
                    p.append(f"{uc}: rezultatul pentru '{alias}' nu e un nume valid ({rez!r})")
            citiri.append(Citire(job=job, valori=dict(valori), parametri=c.get("parametri", "")))
        grupuri.append(Grup(nume=text(g, "nume", ug), citiri=citiri,
                            la_fiecare_s=_numar(g, "la_fiecare_s", 0, p, ug)))

    inst = d.get("instantaneu_la_start", [])
    if not isinstance(inst, list):
        p.append("profil: 'instantaneu_la_start' trebuie să fie o listă de joburi")
        inst = []
    for job in inst:
        if motiv := guard.motiv_refuz(job):
            p.append(f"instantaneu_la_start: {motiv} (doar citire)")

    marcaje, taste = [], set()
    for k, m in enumerate(d.get("marcaj", []), start=1):
        um = f"marcajul {k}"
        chei(m, CHEI_MARCAJ, um)
        et = text(m, "eticheta", um)
        tasta = str(m.get("tasta", ""))
        if tasta and (len(tasta) != 1 or tasta not in "123456789"):
            p.append(f"{um}: 'tasta' trebuie să fie o cifră 1–9")
        elif tasta in taste:
            p.append(f"{um}: tasta '{tasta}' e folosită de două ori")
        taste.add(tasta)
        marcaje.append({"eticheta": et, "tasta": tasta})

    steaguri, nume_steaguri = d.get("steag", []), set()
    for k, s in enumerate(steaguri, start=1):
        us = f"steagul {k} ({s.get('nume', '?')})"
        ns = text(s, "nume", us)
        if ns in nume_steaguri or ns in flags.TIPURI_RECORDER:
            p.append(f"{us}: numele '{ns}' e folosit deja")
        nume_steaguri.add(ns)
        p.extend(f"{us}: {x}" for x in flags.probleme_steag(s, vazute))

    prof = Profil(
        nume=nume, descriere=d.get("descriere", ""), ecu=ecu, grupuri=grupuri,
        segment_minute=_numar(d, "segment_minute", 0, p, "profil"),
        durata_max_minute=_numar(d, "durata_max_minute", 0, p, "profil"),
        cicluri_max=int(_numar(d, "cicluri_max", 0, p, "profil")),
        min_ciclu_ms=_numar(d, "min_ciclu_ms", 0, p, "profil"),
        erori_la_start=bool(d.get("erori_la_start", True)),
        erori_la_stop=bool(d.get("erori_la_stop", True)),
        erori_interval_minute=_numar(d, "erori_interval_minute", 0, p, "profil"),
        instantaneu_la_start=list(inst), marcaje=marcaje, steaguri=list(steaguri), sursa_toml=sursa_toml,
    )
    if p:
        raise ProfilInvalid(f"Profilul '{nume or '?'}' nu se poate încărca:\n- " + "\n- ".join(p))
    return prof


def incarca(cale_sau_nume, director: Path = DIR_PROFILE) -> Profil:
    """Incarca dupa cale (.toml) sau dupa nume din folderul profiles/."""
    cale = Path(cale_sau_nume)
    if cale.suffix.lower() != ".toml":
        cale = Path(director) / f"{cale_sau_nume}.toml"
    if not cale.is_file():
        raise ProfilInvalid(f"Nu găsesc profilul {cale}")
    text = cale.read_text(encoding="utf-8")
    try:
        d = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ProfilInvalid(f"Profilul {cale.name} are o greșeală de format TOML: {e}") from e
    return din_dict(d, sursa_toml=text)


def lista(director: Path = DIR_PROFILE) -> list[str]:
    return sorted(f.stem for f in Path(director).glob("*.toml"))
