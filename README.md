# bmw-mcp

Instrumente de diagnostic BMW (EDIABAS, motor N46 / calculator Bosch MEV9) în Python, **doar citire**:

- `server.py`: server MCP (`bmw-ediabas`) care lasă un asistent AI să citească date de la calculatoarele mașinii.
- `bmwdiag/`: logger cu interfață web locală (profile TOML, salvare automată în CSV, marcaje și steaguri) pentru a înregistra date la rece și la cald.

Interfața și mesajele sunt în limba română.

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

Datele se salvează în `Documents\bmw-data\sesiuni\...`. Folderul se poate schimba cu variabila de mediu `BMW_DATA_DIR` sau cu `--date`.

Cât timp loggerul înregistrează, nu folosi serverul MCP: EDIABAS acceptă o singură sesiune pe port.

## Server MCP

Serverul rulează cu `.venv\Scripts\python.exe server.py` (transport stdio). Variabilele `EDIABAS_BIN` și `EDIABAS_ECU` pot înlocui căile implicite `C:\EDIABAS\Bin` și `C:\EDIABAS\ECU`. Unelte: `ediabas_check`, `list_ecus`, `list_jobs`, `describe_job`, `read_faults`, `run_job`.

## Teste

```
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

`TMODE` (ECU simulat din EDIABAS) permite testul de integrare fără mașină.

## Licență

MIT, vezi `LICENSE`.
