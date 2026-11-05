# bmw-mcp

Instrumente de diagnostic BMW (EDIABAS, motor N46 / calculator Bosch MEV9) în Python, **doar citire**:

- `server.py`: server MCP (`bmw-ediabas`) care lasă un asistent AI să citească date de la calculatoarele mașinii.
- `bmwdiag/`: logger cu interfață web locală (profile TOML, salvare automată în CSV, marcaje și steaguri) pentru a înregistra date la rece și la cald.

Interfața și mesajele sunt în limba română.

Documentație: `docs/SPECIFICATIE.md` (arhitectură, formatul sesiunilor, API, etape) și `docs/JOBURI_MEV9N46L.md` (joburi EDIABAS verificate). Regulile de lucru pentru Claude Code sunt în `CLAUDE.md`.

## Avertisment

Proiectul e făcut pentru **citire**. Garda din `bmwdiag/guard.py` și `server.py` permite doar joburi de tip `STATUS_*`, `*_LESEN`, `IDENT`, `INFO`, `LESE_*` și refuză orice conține `LOESCH`, `SCHREIB`, `STEUERN`, `FLASH`, `PROGRAM`, `RESET`, `SET_`, `WRITE`, `ERASE`, `DELETE`. Nu slăbi garda: o scriere greșită într-un calculator poate strica mașina. Folosești codul pe propria răspundere (vezi licența).

## Cerințe

- Windows, cablu K+DCAN (de ex. cu cip FTDI) și [EDIABAS](https://www.bmw.com) instalat separat (în `C:\EDIABAS`). EDIABAS și fișierele SGBD sunt proprietatea BMW și NU fac parte din acest repo.
- Python 3.13 pe **32 de biți** (`api32.dll` din EDIABAS e pe 32 de biți). Nu merge cu Python pe 64 de biți.
- Pachetele: `pydiabas` și `mcp`. `mcp` se instalează cu `--no-deps`, pentru că `cryptography` nu are pachet pentru Python pe 32 de biți; `setup.bat` face tot (mediu virtual `.venv`, `pydiabas`, `mcp` și dependențele lui).

## Pornire rapidă

```
setup.bat                 :: creează .venv și instalează dependențele
start_logger.bat fake     :: interfața web cu date simulate, fără mașină (http://127.0.0.1:8765)
start_logger.bat          :: mașina reală (cablu în priza OBD, contact pus)
```

### Din telefon (același wifi)

Laptopul rămâne conectat la cablu, iar tu pornești înregistrarea, pui marcaje și vezi starea de pe telefon:

```
start_logger.bat retea          :: mașina reală, accesibil și de pe telefon
start_logger.bat fake retea     :: la fel, cu date simulate
```

În fereastra loggerului apar linkuri de forma `http://192.168.x.x:8765/?cod=xxxxxxxx`. Deschide-l pe telefon (primul link este de obicei cel de wifi); codul se cere o singură dată, apoi rămâne în telefon (cookie), iar adresa nu îl mai conține. Pe laptop nu e nevoie de cod. La prima pornire Windows poate întreba despre firewall: permite accesul pe rețele **private**. Fără `--fara-cod`, din rețea nu se poate face nimic fără cod (nici citit, nici pornit); codul se schimbă la fiecare pornire (sau fixezi unul cu `--cod`). Înregistrarea continuă pe laptop dacă telefonul se oprește sau pierde rețeaua. Laptopul nu adoarme cât înregistrează (nu închide capacul).

Datele se salvează în `Documents\bmw-data\sesiuni\...`. Folderul se poate schimba cu variabila de mediu `BMW_DATA_DIR` sau cu `--date`.

Cât timp loggerul înregistrează, nu folosi serverul MCP: EDIABAS acceptă o singură sesiune pe port.

Pagini ale interfeței web: **Înregistrare** (Start/Stop, salvare în CSV), **Sesiuni** (citirea sesiunilor salvate: grafice, tabel, evenimente, erori, fragment ales cu slider), **Live** (citire în timp real FĂRĂ înregistrare: nu se scrie nimic pe disc decât dacă salvezi explicit; cu profilul `toate_senzorii` vezi valorile de la TOȚI senzorii, descoperiți din calculator) și **Comparare** (rece vs cald). Înregistrarea, citirea live și serverul MCP nu rulează în același timp.

## Rezumat în consolă

Doar citire, fără EDIABAS (merge și cât timp loggerul înregistrează):

```
.venv\Scripts\python.exe -m bmwdiag.rezumat <folder_sesiune sau id> [--date <folder>] [--coloane rpm,tmot] [--evenimente marcaj|steag|eroare] [--json]
```

Arată durata, min/medie/max pe coloană, steagurile pe tip, marcajele și steagurile cu valorile din ±3 s și erorile noi față de start.

## Server MCP

Serverul rulează cu `.venv\Scripts\python.exe server.py` (transport stdio). Variabilele `EDIABAS_BIN` și `EDIABAS_ECU` pot înlocui căile implicite `C:\EDIABAS\Bin` și `C:\EDIABAS\ECU`. Unelte: `ediabas_check`, `list_ecus`, `list_jobs`, `describe_job`, `read_faults`, `run_job`.

## Teste

```
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

`TMODE` (ECU simulat din EDIABAS) permite testul de integrare fără mașină.

## Licență

MIT, vezi `LICENSE`.
