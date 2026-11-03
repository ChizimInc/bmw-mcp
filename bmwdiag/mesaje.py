"""Traducerea erorilor EDIABAS in mesaje clare (romana) pentru jurnal si interfata."""

# (fragment cautat in textul erorii, explicatie); prima potrivire castiga.
# Semnificatiile sunt cele observate pe masina (01.11.2026).
_EXPLICATII = [
    ("IFH-0018", "Portul COM nu se deschide: cablul nu e în laptop sau e pe alt port COM"),
    ("SYS-0010", "Cablul e în laptop, dar calculatorul motorului nu răspunde: cablul nu e pus în mașină?"),
    ("IFH-0006", "Cablul nu e în mașină sau contactul e oprit"),
    ("IFH-0009", "Calculatorul motorului nu a răspuns la timp"),
    ("ERROR_ECU_SERVICE_NOT_SUPPORTED", "Calculatorul motorului nu suportă acest job"),
    ("ERROR_ECU_SUBFUNCTION_NOT_SUPPORTED", "Calculatorul motorului nu suportă parametrii acestui job"),
    ("JOB_STATUS lipseste", "Răspuns fără JOB_STATUS: valorile nu sunt sigure"),
    ("nu este pornita", "Sesiunea de citire nu e pornită"),
]


def explica(eroare: str | None) -> str:
    """'Explicatie (text original)' sau textul original daca nu e cunoscut."""
    if not eroare:
        return ""
    for fragment, explicatie in _EXPLICATII:
        if fragment in eroare:
            return f"{explicatie} ({eroare})"
    return eroare
