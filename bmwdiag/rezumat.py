"""Rezumatul unei sesiuni salvate, in consola (doar citire, fara EDIABAS).

    .venv\\Scripts\\python.exe -m bmwdiag.rezumat <folder_sesiune sau id> [--date <folder>] [--coloane a,b]
                                                [--evenimente marcaj|steag|eroare] [--json]

Strat subtire peste bmwdiag/sesiuni.py: tot ce se citeste si se calculeaza vine de acolo.
Nu scrie niciun fisier si nu modifica sesiunea.
"""
import argparse
import json
import sys
from pathlib import Path

from . import sesiuni
from .recorder import DIR_DATE

NUME_RO = Path(__file__).parent / "static" / "nume_ro.json"
COL_FEREASTRA = ("rpm", "sarcina", "pedala", "clapeta", "tmot")
TIPURI = ("marcaj", "steag", "eroare")
TIPURI_IMPLICITE = ("marcaj", "steag")
COD_EROARE = 2


class Eroare(Exception):
    """Mesaj pentru utilizator (se afiseaza fara traceback, cod de iesire 2)."""


def _nume_ro() -> dict:
    try:
        return json.loads(NUME_RO.read_text(encoding="utf-8")).get("coloane") or {}
    except (OSError, ValueError):
        return {}


def _etichete(nume: dict, coloane_json: dict, col: str) -> tuple[str, str]:
    """(denumire, unitate); ce lipseste din dictionar se afiseaza cu numele brut (unitatea, din coloane.json)."""
    n = nume.get(col) or {}
    unitate = n.get("unitate_afisata")
    if unitate is None:
        unitate = (coloane_json.get(col) or {}).get("unitate") or ""
    return n.get("eticheta") or col, unitate


def _rezolva(arg: str, dir_date) -> tuple[str, Path]:
    """(id, folderul de date) dintr-un id sau din calea unui folder de sesiune."""
    if "/" in arg or "\\" in arg:
        cale = Path(arg).resolve()
        if cale.is_dir() and cale.parent.name == "sesiuni":
            return cale.name, cale.parent.parent
        raise Eroare(f"Nu e un folder de sesiune (așteptat …\\sesiuni\\<id>): {arg}")
    return arg, Path(dir_date)


def construieste(arg: str, dir_date=DIR_DATE, coloane: list[str] | None = None, tip: str | None = None) -> dict:
    """Toata informatia rezumatului, ca dict (aceeasi pentru text si pentru --json)."""
    id_, dd = _rezolva(arg, dir_date)
    try:
        det = sesiuni.incarca(id_, dd)
        inf = sesiuni.info(id_, dd)
    except sesiuni.IdInvalid as e:
        raise Eroare(str(e)) from e
    except sesiuni.NuExista as e:
        raise Eroare(str(e)) from e
    rez = det["rezumat"]
    nume = _nume_ro()
    mm = {}
    cerute = coloane if coloane else list(rez["coloane"])
    for c in cerute:
        if c not in rez["coloane"]:
            raise Eroare(f"Coloană necunoscută sau goală în această sesiune: {c!r}")
        eticheta, unitate = _etichete(nume, det["coloane"], c)
        mm[c] = {"eticheta": eticheta, "unitate": unitate, **rez["coloane"][c]}
    tipuri = (tip,) if tip else TIPURI_IMPLICITE
    ev = [e for e in det["evenimente"] if e["tip"] in tipuri]
    momente = [e["t_rel_s"] for e in ev if e["t_rel_s"] is not None]
    ferestre = iter(sesiuni.masoara(id_, momente, list(COL_FEREASTRA), dd))
    evenimente = [{**e, "fereastra": next(ferestre) if e["t_rel_s"] is not None else {}} for e in ev]
    erori_noi = [{"moment": r["moment"], "nr": e["nr"], "text": e["text"], "simptom": e["simptom"]}
                 for r in det["erori"] for e in r["erori"] if e["nou"]]
    s = det["sesiune"]
    return {
        "id": id_, "stare": inf["stare"], "profil": inf["profil"], "conditie": inf["conditie"], "nota": inf["nota"],
        "start": inf["start"], "durata_s": inf["durata_s"], "randuri": inf["randuri"], "cicluri_pe_s": inf["cicluri_pe_s"],
        "motiv_oprire": inf["motiv_oprire"], "tmot_start": rez.get("tmot_start"), "tmot_stop": rez.get("tmot_stop"),
        "sesiune_json": bool(s), "steaguri": inf["steaguri"], "coloane": mm,
        "coloane_fereastra": {c: dict(zip(("eticheta", "unitate"), _etichete(nume, det["coloane"], c)))
                              for c in COL_FEREASTRA},
        "filtru_evenimente": list(tipuri), "evenimente": evenimente, "erori_noi": erori_noi,
    }


# ---------- afisare ----------
def _fmt(v) -> str:
    if v is None:
        return "–"
    a = abs(v)
    return f"{v:.0f}" if a >= 1000 else f"{v:.1f}" if a >= 100 else f"{v:.2f}"


def _durata(s) -> str:
    if s is None:
        return "?"
    m, sec = divmod(int(round(s)), 60)
    h, m = divmod(m, 60)
    return (f"{h} h {m:02d} min {sec:02d} s" if h else f"{m} min {sec:02d} s") + f" ({s:.1f} s)"


def _moment(t) -> str:
    if t is None:
        return "?"
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


def tabel(antet: list[str], randuri: list[list[str]], stanga: tuple[int, ...] = (0,), indent: str = "  ") -> list[str]:
    """Tabel aliniat din text simplu: coloanele din `stanga` aliniate la stanga, restul la dreapta."""
    lat = [max(len(str(r[i])) for r in [antet] + randuri) for i in range(len(antet))]

    def linie(r):
        return indent + "  ".join(str(c).ljust(lat[i]) if i in stanga else str(c).rjust(lat[i])
                                  for i, c in enumerate(r)).rstrip()
    return [linie(antet), indent + "  ".join("-" * w for w in lat)] + [linie(r) for r in randuri]


def text(r: dict) -> str:
    o = [f"Sesiunea {r['id']}", ""]
    o.append(f"  Stare:        {r['stare']}" + (f" ({r['motiv_oprire']})" if r["motiv_oprire"] else ""))
    o.append(f"  Profil:       {r['profil']}")
    o.append(f"  Condiție:     {r['conditie']}")
    o.append(f"  Început:      {r['start'] or '?'}")
    o.append(f"  Durată:       {_durata(r['durata_s'])}")
    o.append(f"  Rânduri:      {r['randuri'] if r['randuri'] is not None else '?'}")
    cps = r["cicluri_pe_s"]
    o.append(f"  Cicluri/s:    {cps if cps is not None else '?'}")
    if r["tmot_start"] is not None:
        o.append(f"  Temp. motor:  {_fmt(r['tmot_start'])} → {_fmt(r['tmot_stop'])} °C")
    o.append(f"  Notă:         {r['nota'] or '–'}")
    if not r["sesiune_json"]:
        o.append("  Atenție: lipsește sesiune.json; valorile sunt reconstruite din date.")
    o += ["", "Steaguri pe tip:"]
    if r["steaguri"]:
        o += tabel(["Tip", "Număr"], [[k, v] for k, v in sorted(r["steaguri"].items())])
    else:
        o.append("  (niciun steag)")
    o += ["", "Min / medie / max pe coloană:"]
    if r["coloane"]:
        rand = [[c, m["eticheta"], m["unitate"], _fmt(m["min"]), _fmt(m["medie"]), _fmt(m["max"]), m["n"]]
                for c, m in r["coloane"].items()]
        o += tabel(["Coloană", "Denumire", "Unitate", "Min", "Medie", "Max", "N"], rand, stanga=(0, 1, 2))
    else:
        o.append("  (fără date)")
    tip = "/".join(r["filtru_evenimente"])
    o += ["", f"Evenimente ({tip}), cu valorile din ±3 s (înainte = t−3 s, minim în [t−3, t+3], după = t+3 s):"]
    if not r["evenimente"]:
        o.append("  (niciunul)")
    for e in r["evenimente"]:
        o.append(f"  [{_moment(e['t_rel_s'])}] {e['tip']}: {e['detalii']}")
        if e["fereastra"]:
            rand = []
            for c, v in e["fereastra"].items():
                et = r["coloane_fereastra"][c]
                rand.append([f"{et['eticheta']} ({et['unitate']})" if et["unitate"] else et["eticheta"],
                             _fmt(v["inainte"]), _fmt(v["min"]), f"{_moment(v['t_min'])}" if v["t_min"] is not None else "–",
                             _fmt(v["dupa"]), _fmt(v["cadere"])])
            if rand:
                o += tabel(["Mărime", "înainte", "minim", "la", "după", "cădere"], rand, indent="      ")
    o += ["", "Erori noi față de start:"]
    if r["erori_noi"]:
        def moment(m):  # "1801" = citirea de la 1801 s
            return f"la {_moment(float(m))}" if m.replace(".", "", 1).isdigit() else m
        o += tabel(["Moment", "Nr.", "Text"], [[moment(e["moment"]), e["nr"], e["text"] or ""] for e in r["erori_noi"]],
                   stanga=(0, 2))
    else:
        o.append("  (nicio eroare nouă)")
    return "\n".join(o)


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m bmwdiag.rezumat",
                                 description="Rezumatul unei sesiuni salvate (doar citire).")
    ap.add_argument("sesiune", help="calea folderului sesiunii sau doar id-ul ei")
    ap.add_argument("--date", default=str(DIR_DATE), help="folderul de date (implicit: Documents\\bmw-data sau BMW_DATA_DIR)")
    ap.add_argument("--coloane", help="doar aceste coloane în tabelul min/medie/max, separate prin virgulă")
    ap.add_argument("--evenimente", choices=TIPURI, help="doar evenimentele de acest tip (implicit: marcaj și steag)")
    ap.add_argument("--json", action="store_true", help="aceeași informație ca JSON, fără decor")
    a = ap.parse_args(argv)
    coloane = [c.strip() for c in a.coloane.split(",") if c.strip()] if a.coloane else None
    try:
        r = construieste(a.sesiune, a.date, coloane, a.evenimente)
    except Eroare as e:
        print(f"Eroare: {e}", file=sys.stderr)
        return COD_EROARE
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else text(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
