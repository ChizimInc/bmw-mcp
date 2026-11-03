"""Steaguri automate (marcaje puse de logger), din sectiunea [[steag]] a profilului.

Tipuri pe valori (evaluate la fiecare rand):
- cadere:     `camp` scade cu cel putin `cu` fata de maximul din ultimele `in_s` secunde,
              cu toate `conditii` adevarate (ex. "pedala < 2"). Se rearmeaza cand caderea
              ajunge sub `cu`/2 (o cuplare = un singur steag, chiar cu zgomot in jurul pragului).
- trece_prag: `camp` trece peste / sub unul din `praguri` (cu `histereza`, implicit 1).
- sub/peste:  `camp` sta sub / peste `valoare` cel putin `timp_s` secunde (implicit 0).
Tipuri puse de recorder (nu se declara in profil, sunt mereu active):
- eroare_noua, conexiune_pierduta, conexiune_restabilita.
"""
import collections
import operator
import re

TIPURI = {
    # tip: (chei obligatorii, chei optionale)
    "cadere": ({"camp", "cu", "in_s"}, {"conditii"}),
    "trece_prag": ({"camp", "praguri"}, {"histereza", "conditii"}),
    "sub": ({"camp", "valoare"}, {"timp_s", "conditii"}),
    "peste": ({"camp", "valoare"}, {"timp_s", "conditii"}),
}
TIPURI_RECORDER = ("eroare_noua", "conexiune_pierduta", "conexiune_restabilita")
_OPERATORI = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
              "==": operator.eq, "!=": operator.ne}
_CONDITIE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")


def _este_numar(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parseaza_conditie(text: str):
    """'pedala < 2' -> ('pedala', '<', 2.0) sau None daca nu e valida."""
    m = _CONDITIE.match(text) if isinstance(text, str) else None
    return (m.group(1), m.group(2), float(m.group(3))) if m else None


def probleme_steag(s: dict, aliasuri: set) -> list[str]:
    """Validarea unui [[steag]]; lista goala = valid."""
    p = []
    tip = s.get("tip")
    if tip in TIPURI_RECORDER:
        return [f"tipul '{tip}' e pus automat de logger; nu-l declara în profil"]
    if tip not in TIPURI:
        return [f"tip necunoscut '{tip}' (merg: {', '.join(TIPURI)})"]
    obligatorii, optionale = TIPURI[tip]
    for k in sorted(obligatorii - set(s)):
        p.append(f"lipsește '{k}' (obligatoriu pentru tipul '{tip}')")
    for k in sorted(set(s) - obligatorii - optionale - {"nume", "tip"}):
        p.append(f"cheie necunoscută '{k}' pentru tipul '{tip}'")
    camp = s.get("camp")
    if camp is not None and camp not in aliasuri:
        p.append(f"câmpul '{camp}' nu e un alias din profil")
    for k in ("cu", "in_s", "valoare", "timp_s", "histereza"):
        if k in s and not _este_numar(s[k]):
            p.append(f"'{k}' trebuie să fie număr")
    for k in ("cu", "in_s"):
        if _este_numar(s.get(k)) and s[k] <= 0:
            p.append(f"'{k}' trebuie să fie > 0")
    if "praguri" in s and (not isinstance(s["praguri"], list) or not s["praguri"]
                           or not all(_este_numar(x) for x in s["praguri"])):
        p.append("'praguri' trebuie să fie o listă de numere")
    conditii = s.get("conditii", [])
    if not isinstance(conditii, list):
        p.append("'conditii' trebuie să fie o listă, ex. [\"pedala < 2\"]")
        conditii = []
    for c in conditii:
        pc = parseaza_conditie(c)
        if pc is None:
            p.append(f"condiția {c!r} nu e de forma \"alias < număr\"")
        elif pc[0] not in aliasuri:
            p.append(f"condiția {c!r} folosește un alias care nu există")
    return p


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


class _Steag:
    def __init__(self, d: dict):
        self.nume = d["nume"]
        self.camp = d["camp"]
        self.conditii = [parseaza_conditie(c) for c in d.get("conditii", [])]

    def conditii_ok(self, cunoscute: dict) -> bool:
        for alias, op, prag in self.conditii:
            v = cunoscute.get(alias)
            if not _este_numar(v) or not _OPERATORI[op](v, prag):
                return False
        return True


class _Cadere(_Steag):
    def __init__(self, d):
        super().__init__(d)
        self.cu, self.in_s = float(d["cu"]), float(d["in_s"])
        self.fereastra = collections.deque()   # (t, valoare)
        self.armat = True

    def evalueaza(self, t, v, cunoscute):
        self.fereastra.append((t, v))
        while self.fereastra and t - self.fereastra[0][0] > self.in_s:
            self.fereastra.popleft()
        t_max, v_max = max(self.fereastra, key=lambda x: x[1])
        scadere = v_max - v
        if scadere >= self.cu:
            if self.armat and self.conditii_ok(cunoscute):
                self.armat = False
                return (f"{self.camp} a scăzut cu {_fmt(scadere)} ({_fmt(v_max)} → {_fmt(v)}) "
                        f"în {t - t_max:.2f} s")
        elif scadere < self.cu / 2:
            # histereza: in revenire, scaderea oscileaza in jurul pragului (zgomot); rearmam doar
            # dupa ce turatia si-a revenit cel putin la jumatate, ca o cuplare sa dea un singur steag
            self.armat = True
        return None


class _TrecePrag(_Steag):
    def __init__(self, d):
        super().__init__(d)
        self.praguri = sorted(float(x) for x in d["praguri"])
        self.h = float(d.get("histereza", 1.0))
        self.peste = None  # prag -> True/False, din prima valoare

    def evalueaza(self, t, v, cunoscute):
        if self.peste is None:
            self.peste = {p: v >= p for p in self.praguri}
            return None
        mesaje = []
        for p in self.praguri:
            if not self.peste[p] and v >= p:
                self.peste[p] = True
                mesaje.append(f"{self.camp} a trecut peste {_fmt(p)} ({_fmt(v)})")
            elif self.peste[p] and v < p - self.h:
                self.peste[p] = False
                mesaje.append(f"{self.camp} a coborât sub {_fmt(p)} ({_fmt(v)})")
        if mesaje and self.conditii_ok(cunoscute):
            return "; ".join(mesaje)
        return None


class _SubPeste(_Steag):
    def __init__(self, d, sub: bool):
        super().__init__(d)
        self.sub = sub
        self.valoare = float(d["valoare"])
        self.timp_s = float(d.get("timp_s", 0))
        self.t_inceput = None
        self.semnalat = False

    def evalueaza(self, t, v, cunoscute):
        dincolo = v < self.valoare if self.sub else v > self.valoare
        if not dincolo:
            self.t_inceput, self.semnalat = None, False
            return None
        if self.t_inceput is None:
            self.t_inceput = t
        if not self.semnalat and t - self.t_inceput >= self.timp_s and self.conditii_ok(cunoscute):
            self.semnalat = True
            cuvant = "sub" if self.sub else "peste"
            return f"{self.camp} = {_fmt(v)}, {cuvant} {_fmt(self.valoare)} de {t - self.t_inceput:.1f} s"
        return None


def _construieste(d: dict):
    tip = d["tip"]
    if tip == "cadere":
        return _Cadere(d)
    if tip == "trece_prag":
        return _TrecePrag(d)
    if tip in ("sub", "peste"):
        return _SubPeste(d, sub=(tip == "sub"))
    raise ValueError(f"tip de steag necunoscut: {tip}")


class MotorSteaguri:
    """Primeste randurile pe rand; intoarce steagurile aparute [(nume, detalii)]."""

    def __init__(self, definitii: list[dict]):
        self.steaguri = [_construieste(d) for d in definitii]
        self.cunoscute: dict = {}   # ultima valoare stiuta pe alias (grupurile lente nu sunt in fiecare rand)

    def evalueaza(self, t: float, valori: dict) -> list[tuple[str, str]]:
        self.cunoscute.update({k: v for k, v in valori.items() if _este_numar(v)})
        rez = []
        for s in self.steaguri:
            v = valori.get(s.camp)   # doar valori citite in acest rand
            if _este_numar(v):
                detalii = s.evalueaza(t, float(v), self.cunoscute)
                if detalii:
                    rez.append((s.nume, detalii))
        return rez


def compara_erori(anterioare: list[dict], acum: list[dict]) -> list[str]:
    """Diferente intre doua citiri FS_LESEN (seturi de date), dupa F_ORT_NR si F_VORHANDEN_NR."""
    def pe_nr(seturi):
        return {int(s["F_ORT_NR"]): s for s in seturi if _este_numar(s.get("F_ORT_NR"))}

    vechi, noi = pe_nr(anterioare), pe_nr(acum)
    mesaje = []
    for nr, s in noi.items():
        eticheta = f"{nr:04X} {s.get('F_ORT_TEXT', '')}".strip()
        if nr not in vechi:
            mesaje.append(f"eroare nouă {eticheta} ({s.get('F_VORHANDEN_TEXT', '?')})")
        elif s.get("F_VORHANDEN_NR") != vechi[nr].get("F_VORHANDEN_NR"):
            mesaje.append(f"eroarea {eticheta} și-a schimbat starea: {vechi[nr].get('F_VORHANDEN_TEXT', '?')} "
                          f"→ {s.get('F_VORHANDEN_TEXT', '?')}")
    return mesaje
