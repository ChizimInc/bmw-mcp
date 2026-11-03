"""Jurnal live: ultimele linii in memorie (pentru interfata) + fisier jurnal.txt."""
import collections
import threading
from datetime import datetime


class Jurnal:
    def __init__(self, max_linii: int = 200, ecou=None):
        self._linii = collections.deque(maxlen=max_linii)  # (numar, text)
        self._nr = 0
        self._fisier = None
        self._ecou = ecou            # ex. print in consola
        self._lock = threading.Lock()

    def deschide_fisier(self, cale):
        """De acum, liniile noi merg si in fisier (jurnalul in memorie e comun tuturor sesiunilor)."""
        with self._lock:
            self._fisier = open(cale, "a", encoding="utf-8")

    def inchide_fisier(self):
        with self._lock:
            if self._fisier:
                self._fisier.close()
                self._fisier = None

    def scrie(self, text: str, nivel: str = "info") -> str:
        ora = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        eticheta = {"info": "", "avertisment": "AVERTISMENT: ", "eroare": "EROARE: "}.get(nivel, "")
        linie = f"{ora} {eticheta}{text}"
        with self._lock:
            self._nr += 1
            self._linii.append((self._nr, linie))
            if self._fisier:
                self._fisier.write(linie + "\n")
                self._fisier.flush()
        if self._ecou:
            self._ecou(linie)
        return linie

    def de_la(self, n: int = 0) -> list[tuple[int, str]]:
        """Liniile cu numar > n (cele mai vechi primele)."""
        with self._lock:
            return [x for x in self._linii if x[0] > n]
