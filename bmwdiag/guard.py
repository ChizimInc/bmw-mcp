"""Garda doar-citire pentru joburile EDIABAS.

Regulile sunt copiate exact din server.py. Se aplica la incarcarea profilului
si la fiecare apel (EdiabasClient, FakeSource, ReplaySource).
"""
import re

# Joburi permise: citiri si interogari ale descrierii SGBD-ului
ALLOWED = re.compile(r"^(STATUS_\w+|\w+_LESEN(_DETAIL)?|LESE_\w+|IDENT\w*|INFO|_\w+)$")
# Orice job cu aceste cuvinte este refuzat chiar daca trece de lista de mai sus
DENIED = re.compile(r"LOESCH|SCHREIB|STEUERN|FLASH|PROGRAM|RESET|CODIER.*(SCHREIB|LOESCH)|SET_|WRITE|ERASE|DELETE", re.I)


class JobBlocat(Exception):
    """Jobul nu este o citire si a fost refuzat."""


def motiv_refuz(job) -> str | None:
    """None daca jobul e permis, altfel textul motivului."""
    if not isinstance(job, str) or not job:
        return "numele jobului lipseste sau nu e text"
    if DENIED.search(job):
        return f"jobul '{job}' contine un cuvant interzis (scriere/stergere/comanda)"
    # fullmatch, nu match: '$' din ALLOWED ar accepta si un '\n' la final
    if not ALLOWED.fullmatch(job):
        return f"jobul '{job}' nu este in lista de citiri permise"
    return None


def este_permis(job) -> bool:
    return motiv_refuz(job) is None


def verifica(job) -> str:
    """Intoarce jobul daca e permis, altfel ridica JobBlocat."""
    motiv = motiv_refuz(job)
    if motiv:
        raise JobBlocat(f"Refuzat (doar citire): {motiv}.")
    return job
