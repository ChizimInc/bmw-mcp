# Proiect: logger și server MCP de diagnostic BMW (EDIABAS, N46 / Bosch MEV9)

Repo PUBLIC. Nu pune aici VIN, kilometraj, istoric de erori, căi cu numele de utilizator sau alte date despre o mașină anume. Acestea merg în `local/` sau `CLAUDE.local.md` (ignorate de git).

Citește, în ordine:
1. `README.md`: ce face proiectul și cum se pornește.
2. `docs/SPECIFICATIE.md`: arhitectura loggerului, formatul fișierelor, API, etape și criterii de acceptare.
3. `docs/JOBURI_MEV9N46L.md`: joburile EDIABAS verificate și rezultatele lor.
4. Dacă există (nu e în git): `CLAUDE.local.md` și `local/BMW_CONTEXT.md` (mașina concretă, istoric, ipoteze).

Reguli care nu se negociază:
- Python: DOAR `.venv\Scripts\python.exe` (Python 3.13 pe 32 de biți, necesar pentru `C:\EDIABAS\Bin\api32.dll`). Nu folosi un Python pe 64 de biți. Nu instala pachete global. Evită pachetele fără wheel win32.
- DOAR CITIRE pe mașină. Respectă garda din `server.py` / `bmwdiag/guard.py`. Niciodată `STEUERN_*`, `*_LOESCHEN`, `*_SCHREIBEN`, `FLASH_*`, `SET_*`, ștergere de erori sau codări.
- Varianta ECU: `MEV9N46L` (grupul `D_MOTOR` rezolvă la ea). NU `MSV70`.
- Nu modifica `C:\EDIABAS` (INI-uri, SGBD) fără acordul explicit al proprietarului.
- Nu strica `server.py`: e serverul MCP `bmw-ediabas` folosit din chat.
- EDIABAS = o singură sesiune pe port: loggerul și serverul MCP nu citesc în același timp.
- Fără mașină: testează cu ECU-ul simulat `TMODE` (job `LESE_INTERFACE_TYP`) și cu surse de date false (`FakeSource`, `ReplaySource`).
- Datele se salvează în afara repo-ului (`Documents\bmw-data` sau `BMW_DATA_DIR`). Nu le comite.
- Interfața și mesajele sunt în română.
- Teste: `.venv\Scripts\python.exe -m unittest discover -s tests -t .`

Git:
- Lucrăm DOAR pe branch-ul `dev`. Nu face commit și nu face push direct pe `main`.
- Push doar când proprietarul cere. `main` se actualizează doar printr-un PR din `dev`, aprobat de proprietar.
- Înainte de commit verifică `git status`: nimic din `local/`, `CLAUDE.local.md`, `bmw-data/`, CSV-uri de sesiune sau fișiere cu VIN.

După fiecare etapă: actualizează documentația. Ce ține de mașina concretă (cicluri/s măsurate, erori, observații) merge în `local/BMW_CONTEXT.md`; ce e general (format, API, joburi noi) merge în `docs/`.
