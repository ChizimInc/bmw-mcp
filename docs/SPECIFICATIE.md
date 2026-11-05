# Specificație: logger de diagnostic EDIABAS (BMW N46 / Bosch MEV9) cu interfață web locală

Document public. Descrie CE construim și CUM. Numerotarea secțiunilor e păstrată din planul original; secțiunea 4 (joburile verificate) e în `docs/JOBURI_MEV9N46L.md`. Notele despre o mașină anume (istoric, simptome, ipoteze, planul de analiză) NU sunt în repo; stau local.

## 0. Scopul

Un logger local care înregistrează, fără un asistent AI în buclă, date de la calculatorul motorului (DME) în timpul mersului și la ralanti, la rece și la cald, pentru analiză ulterioară (compararea sesiunilor rece vs cald).

Cerințe de design (decise):

1. Interfață web locală, în browser. Ecranul de înregistrare NU are grafice: doar jurnal live, stare și ultimele valori, ca să se vadă că nu s-a blocat și că se scriu date. Graficele sunt în paginile Sesiuni (date salvate, secțiunea 13) și Live (citire fără înregistrare, secțiunea 14).
2. Profile declarative (fișiere TOML), alese din interfață, ca tipul de test să se schimbe fără cod.
3. Între datele citite trebuie să fie și sarcina motorului (cât de încărcat e motorul acum).
4. Un profil de lungă durată (pornit la începutul drumului, aproximativ 30 de minute prin oraș).
5. Salvare automată, steaguri (marcaje manuale și automate), teste la rece și la cald.

## 1. Mediul

- Laptop Windows 11 x64. EDIABAS 7.3.0 în `C:\EDIABAS` (`Bin\api32.dll` e pe 32 de biți). INPA 5.0.6 în `C:\EC-APPS\INPA` (opțional).
- Interfață: `C:\EDIABAS\Bin\EDIABAS.INI` → `Interface = STD:OBD`; `C:\EDIABAS\Bin\obd.ini` → `Port=Com1` (portul cablului).
- Cablu: K+DCAN cu cip FTDI, latency timer 1 ms.
- Python: 3.13 pe 32 de biți. NU se folosește un Python pe 64 de biți.
- Mediu virtual: `.venv` în rădăcina proiectului (creat de `setup.bat`). Conține `pydiabas` 1.2.0 și `mcp` 1.30.0 (instalat `--no-deps`, fiindcă `cryptography` nu are pachet pentru Python 32-bit), plus dependențele mcp: `starlette`, `uvicorn`, `pydantic`, `anyio` etc.
- Folderul de date: `Documents\bmw-data` (schimbabil cu `BMW_DATA_DIR` sau `--date`).
- Calculatorul motorului: Bosch MEV9 pentru N46, variantă SGBD `MEV9N46L`. Grupul `D_MOTOR` rezolvă automat la această variantă. NU `MSV70` (variantă greșită, dă valori absurde).
- Comunicarea e KWP2000 pe K-line (telegramele arată `83 12 F1 22 ...`), deci lentă: câteva citiri de job pe secundă. Viteza reală e măsurată de logger (cicluri/s în `sesiune.json`).

## 2. Constrângeri dure

- Totul rulează în Python-ul de 32 de biți din `.venv`. Nu instala pachete care cer compilare (fără wheel win32). Preferă biblioteca standard.
- DOAR CITIRE. Refolosește exact regulile din `server.py`:
  - permise: `^(STATUS_\w+|\w+_LESEN(_DETAIL)?|LESE_\w+|IDENT\w*|INFO|_\w+)$`
  - refuzate (chiar dacă trec mai sus): `LOESCH|SCHREIB|STEUERN|FLASH|PROGRAM|RESET|CODIER.*(SCHREIB|LOESCH)|SET_|WRITE|ERASE|DELETE` (fără diferență de majuscule)
  - Garda se aplică la încărcarea profilului ȘI la fiecare apel. Un profil cu job refuzat nu se încarcă.
- Nu ștergi erori, nu codezi, nu modifici `C:\EDIABAS` fără acordul explicit al proprietarului.
- EDIABAS acceptă o singură sesiune pe port. Cât timp rulează loggerul (înregistrare SAU citire live), serverul MCP `bmw-ediabas` (folosit din chat) nu trebuie să citească. Comportamentul la conflict nu a fost testat; presupune conflict și afișează un avertisment clar în interfață și în README.
- `stdout` nu e folosit pentru protocol aici (spre deosebire de server.py), dar loggerul scrie jurnalul și în fișier.
- Fără date personale în fișierele partajate: rezultatele `AIF_LESEN` conțin VIN-ul. Se pot salva local în instantaneu, dar nu se pun în rezumate sau în documente de proiect.

## 3. PyDIABAS: ce știm sigur

- Import: `from pydiabas import PyDIABAS`. Înainte de import, adaugă `C:\EDIABAS\Bin` în `PATH` și apelează `os.add_dll_directory(...)` (vezi `server.py`).
- Sesiune: `p = PyDIABAS(); p.start()` ... `p.end()`, sau `with PyDIABAS() as p:`. `p.reset()` = end + start.
- Job: `res = p.job(ecu, job, parameters="", result_filter="")`. `parameters` și `result_filter` sunt șiruri separate prin `;`.
- La eșec ridică `StateError` (ex.: `IFH-0018: INITIALIZATION ERROR` = port COM indisponibil; `SYS-0010: INITIALIZATION ERROR` = ECU nu răspunde; `IFH-0006: COMMAND NOT ACCEPTED` = cablu nepus în mașină sau contact oprit).
- Rezultat: `res.as_dicts()` → listă de dicționare: elementul 0 e setul de sistem (OBJECT, SAETZE, JOBNAME, VARIANTE, JOBSTATUS...), următoarele sunt seturile de date. Valorile pot fi `bytes` (decodează ca în `server.py::_clean`). `JOB_STATUS` = `"OKAY"` la succes; altfel text de eroare, de ex. `ERROR_ECU_SUBFUNCTION_NOT_SUPPORTED__INVALID_FORMAT`, `ERROR_ECU_SERVICE_NOT_SUPPORTED`.
- `result_filter` reduce mult răspunsul și trebuie folosit în bucla rapidă.
- ECU simulat `TMODE` (job `LESE_INTERFACE_TYP`, rezultat `TYP` = `b'OBD'`) merge fără mașină și fără cablu: folosește-l pentru testul de integrare EDIABAS acasă.
- Pentru viteză, loggerul ține O SINGURĂ sesiune deschisă pe toată durata înregistrării (nu `with` per job, cum face server.py). La erori repetate face `reset()`.

## 4. Joburi și rezultate verificate

Vezi `docs/JOBURI_MEV9N46L.md`.

## 5. Arhitectura

```
bmw-mcp/
  server.py                 # serverul MCP existent; NU îl strica
  bmwdiag/
    __init__.py
    guard.py                # regulile doar-citire (copiate din server.py, apoi server.py le poate importa)
    ediabas_client.py       # sesiune persistentă PyDIABAS, run_job(), decodare, retry/reset
    sources.py              # EdiabasSource (real) + FakeSource (date sintetice) + ReplaySource (CSV vechi)
    profiles.py             # încărcare și validare TOML (tomllib din biblioteca standard)
    flags.py                # motorul de reguli pentru steaguri automate
    recorder.py             # bucla de citire, scrierea CSV, segmente, evenimente, instantanee
    webapp.py               # server HTTP (biblioteca standard) + API JSON
    static/index.html, app.js, style.css
  profiles/*.toml
  start_logger.bat          # pornește aplicația cu .venv\Scripts\python.exe și deschide browserul
  tests/
```

Decizii:
- Server web: `http.server.ThreadingHTTPServer` din biblioteca standard, legat la `127.0.0.1:8765` (opțional `--host 0.0.0.0` pentru telefon, implicit OPRIT). Pagina face polling la 1 s pe API. Fără framework (evită probleme de pachete pe 32 de biți). (Alternativa: `starlette`/`uvicorn` sunt deja în `.venv` din cauza mcp; folosește-le doar dacă biblioteca standard devine incomodă.)
- Bucla de citire rulează într-un fir separat; interfața doar citește starea printr-un obiect protejat cu lock și trimite comenzi (start/stop/marcaj).
- O singură instanță: la pornire creează un fișier de blocare în `bmw-data` și refuză a doua pornire.
- Laptopul nu trebuie să adoarmă cât înregistrează: `ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` la start, resetat la stop.

## 6. Profile (TOML)

Fiecare profil e un fișier în `profiles/`. Validare strictă la încărcare (câmpuri lipsă, joburi refuzate de gardă, alias-uri duplicate → eroare clară în interfață).

```toml
nume = "eveniment_rapid"
descriere = "Bucla cea mai rapidă: cuplarea ambreiajului, accelerări. Pornește-l înainte de manevră."
ecu = "MEV9N46L"
segment_minute = 0            # 0 = un singur fișier
durata_max_minute = 0         # 0 = până la Stop
erori_la_start = true
erori_la_stop = true
erori_interval_minute = 0     # 0 = doar la start/stop
instantaneu_la_start = ["IDENT", "ZIF_LESEN", "DATEN_REFERENZ_LESEN", "STATUS_GEMISCH", "STATUS_GEBERRAD_ADAPTION", "STATUS_FUNKTIONSSTATI", "STATUS_READINESS"]

[[grup]]
nume = "rapid"
la_fiecare_s = 0              # 0 = în fiecare ciclu
  [[grup.citire]]
  job = "STATUS_MESSWERTE"
  valori = { rpm = "STAT_NMOT_WERT", rpm_tinta = "STAT_NSOL_WERT", tmot = "STAT_TMOT_WERT", taer = "STAT_TANS_WERT", ub = "STAT_UB_WERT", viteza = "STAT_VFZG_WERT", upedala = "STAT_UPWG_WERT", maf = "STAT_MSHFM_WERT", cuplu = "STAT_MIIST_WERT", fr1 = "STAT_FR_WERT", fr2 = "STAT_FR2_WERT", te = "STAT_TE_WERT", clapeta = "STAT_WDKBA_WERT", avans = "STAT_ZWOUT_WERT", came_ev = "STAT_WNWKWA_WERT", came_adm = "STAT_WNWKWE_WERT" }
  [[grup.citire]]
  job = "STATUS_FASTA2"
  valori = { sarcina = "STAT_RL_WERT", sarcina_tinta = "STAT_RLSOL_WERT", pedala = "STAT_WPED_WERT", te2 = "STAT_TE2_WERT", llr_int = "STAT_DMLLRI_WERT" }

[[grup]]
nume = "lent"
la_fiecare_s = 5
  [[grup.citire]]
  job = "STATUS_LAUFUNRUHE"
  valori = { lu1 = "STAT_LUTSFI1_WERT", lu2 = "STAT_LUTSFI2_WERT", lu3 = "STAT_LUTSFI3_WERT", lu4 = "STAT_LUTSFI4_WERT" }

[[marcaj]]
eticheta = "Cuplez ambreiajul"
tasta = "1"
[[marcaj]]
eticheta = "Simt problema"
tasta = "2"
[[marcaj]]
eticheta = "Accelerez tare"
tasta = "3"

[[steag]]
nume = "cadere_la_cuplare"
tip = "cadere"                # valoarea scade cu cel puțin `cu` în cel mult `in_s`
camp = "rpm"
cu = 150
in_s = 1.5
conditii = ["pedala < 2", "viteza < 15"]
[[steag]]
nume = "tmot_prag"
tip = "trece_prag"
camp = "tmot"
praguri = [40, 60, 80]
[[steag]]
nume = "tensiune_mica"
tip = "sub"
camp = "ub"
valoare = 12.0
timp_s = 3
```

Alias-urile (`rpm`, `sarcina`...) devin numele coloanelor. Unitățile se iau din rezultatul `..._EINH` la prima citire și se scriu în `coloane.json`.

Profile inițiale de livrat (toate cu cele trei marcaje de mai sus sau adaptate):

1. `eveniment_rapid`: doar grupul „rapid" (MESSWERTE + FASTA2) și LAUFUNRUHE la 5 s. Pentru cuplarea ambreiajului și accelerări, la rece și la cald.
2. `drum_lung_oras`: aceleași valori + sondele lambda (4 joburi) și FUNKTIONSSTATI la 10 s; `segment_minute = 10`, `erori_interval_minute = 10`. Pentru 30+ minute prin oraș.
3. `ralanti_incalzire`: MESSWERTE + FASTA2 la fiecare ciclu, LAUFUNRUHE + sonde + FUNKTIONSSTATI + VVT la 10 s, GEMISCH la 60 s; steag `tmot_prag` la 40/60/70/80/90. Pentru pornirea la rece până la cald, mașina pe loc.
4. `instantaneu_complet`: o singură trecere prin toate joburile utile de la secțiunea 4 (inclusiv identificare și erori, fără AIF în rezumat), apoi se oprește singur. Util la începutul fiecărei zile de test.

## 7. Ciclul de citire

- Un ciclu = rulează grupurile scadente, în ordine, apoi scrie UN rând.
- Coloanele unui grup lent rămân GOALE în rândurile în care grupul nu a fost citit (nu copia ultima valoare).
- Fiecare rând are: `t_iso` (ora locală cu milisecunde), `t_rel_s` (secunde de la start, din ceas monoton), `ciclu`, `ciclu_ms` (durata ciclului), coloanele de valori, `marcaj` (text, dacă s-a apăsat în acel ciclu), `steaguri` (listă separată cu `;`).
- Job eșuat: celulele lui rămân goale, eroarea merge în jurnal și `evenimente.csv`, iar contorul de erori crește. Ciclul continuă.
- 3 cicluri consecutive fără niciun job reușit → steag `conexiune_pierduta`, `reset()` cu așteptare crescătoare (1 s, 2 s, 5 s, apoi la 5 s). La prima citire reușită → `conexiune_restabilita`.
- Fără pauze artificiale: ciclul rulează cât de repede permite K-line. Opțional `min_ciclu_ms` în profil.
- Măsoară și raportează în interfață: cicluri/s, durata medie a fiecărui job.

## 8. Fișierele unei sesiuni

Folder nou: `Documents\bmw-data\sesiuni\<AAAA-LL-ZZ_HHMMSS>_<profil>_<rece|cald|necunoscut>\`

- `sesiune.json`: profilul (copie integrală), condiția (rece/cald), nota scrisă de proprietar la start, versiunea aplicației, ora start/stop, numărul de rânduri, motivul opririi.
- `date_001.csv`, `date_002.csv`, …: datele, câte un fișier pe segment. Antet cu alias-uri. Separator virgulă, punct zecimal, UTF-8. `flush()` după fiecare rând, `os.fsync()` cel puțin la 5 s. La pornirea unui segment nou, antetul se rescrie.
- `coloane.json`: alias → job, rezultat, unitate.
- `evenimente.csv`: `t_iso, t_rel_s, tip (marcaj|steag|eroare|stare), detalii`.
- `erori_start.json`, `erori_stop.json`, `erori_<t_rel>.json`: rezultatul `FS_LESEN` (și `FS_LESEN_DETAIL` pentru fiecare eroare găsită). La diferență față de start → steag `eroare_noua`.
- `instantaneu_start.json`: rezultatul joburilor din `instantaneu_la_start`.
- `jurnal.txt`: tot ce apare în jurnalul din interfață.
- Sesiunile salvate din citirea live (secțiunea 14, Etapa 13) au doar `sesiune.json` (cu `origine: "live"`), `date_001.csv`, `evenimente.csv` și `coloane.json`; nu au erori, instantaneu, jurnal sau statistici de joburi.
- La Stop (sau oprire neașteptată, prin `atexit` și tratarea Ctrl+C) se închid fișierele corect și se scrie `sesiune.json` final.

## 9. Interfața web (în română)

Aceasta descrie ecranul de ÎNREGISTRARE. Vizualizarea sesiunilor salvate (listă, alegere, afișare în format ușor de citit) e în secțiunea 13.

O singură pagină:
- Sus: alegere profil (listă din `profiles/`), condiție (rece / cald / necunoscut), câmp de notă, butoane Start și Stop, buton „Citește erorile acum".
- Panou de stare, actualizat la 1 s: stare (oprit / pornește / înregistrează / reconectare / eroare), profil, timp scurs, rânduri scrise, cicluri/s, „ultima citire reușită acum X s" (VERDE sub 2 s, GALBEN 2–5 s, ROȘU peste 5 s), număr de erori, folderul sesiunii.
- Ultimele valori: un tabel text simplu alias → valoare → unitate (fără grafice).
- Butoane de marcaj din profil, cu tastele 1–9 în pagină.
- Jurnal live: ultimele 200 de linii (start, segmente noi, steaguri, erori, reconectări), cel mai nou sus.
- Avertisment permanent: „Cât timp înregistrezi, nu folosi serverul MCP din chat."

API (JSON): `GET /api/stare`, `GET /api/jurnal?de_la=N`, `GET /api/profile`, `POST /api/start {profil, conditie, nota}`, `POST /api/stop`, `POST /api/marcaj {eticheta}`, `POST /api/erori`.

`start_logger.bat`: rulează `.venv\Scripts\python.exe -m bmwdiag.webapp` din folderul `bmw-mcp` și deschide `http://127.0.0.1:8765` în browser.

## 10. Etape și criterii de acceptare

Etapa 0 – Fundația
- `guard.py` cu testele lui (joburi permise și refuzate, inclusiv `STEUERN_*`, `FS_LOESCHEN`, `FLASH_*`, `SET_*`).
- `ediabas_client.py`: sesiune persistentă, `run(job, filtru, parametri)` cu decodare (`bytes` → text sau `hex:`), detectarea `JOB_STATUS`.
- `FakeSource` care generează valori plauzibile (turație care scade la „cuplare", temperatură care crește) și `ReplaySource` care redă un CSV.
- Criteriu: testele trec; `TMODE` funcționează prin `ediabas_client` acasă, fără mașină.

Etapa 1 – Logger în consolă
- `python -m bmwdiag.recorder --profil eveniment_rapid --sursa fake|ediabas`, cu scrierea completă a folderului de sesiune (secțiunea 8).
- Criteriu: cu `fake` scrie un CSV corect 2 minute; în mașină (contact pus, motor oprit, apoi pornit) MĂSOARĂ cicluri/s pentru profilul `eveniment_rapid` și scrie rezultatul în `BMW_CONTEXT.md`.

Etapa 2 – Interfața web
- Toate elementele din secțiunea 9.
- Criteriu: cu `fake`, Start/Stop/marcaje/jurnal merg din browser; închiderea browserului NU oprește înregistrarea; repornirea paginii arată starea curentă.

Etapa 3 – Profile, steaguri, erori
- Cele 4 profile din secțiunea 6, motorul de steaguri (`cadere`, `trece_prag`, `sub`, `peste`, `eroare_noua`, `conexiune_*`), citirea erorilor la start/stop/interval/la cerere.
- Criteriu: cu `fake`, steagul `cadere_la_cuplare` apare la căderea simulată; un profil cu un job refuzat e respins cu mesaj clar.

Etapa 4 – Robustețe pentru drumul lung
- Segmente, reconectare automată, prevenirea adormirii, blocarea a două instanțe, oprire curată.
- Criteriu: 30 de minute cu `fake` fără pierderi; cu mașina, scoaterea și reintroducerea cablului produce `conexiune_pierduta` și apoi `conexiune_restabilita`, fără să se oprească sesiunea.

Etapa 5 – Rezumat în consolă (se face pe `bmwdiag/sesiuni.py`, vezi secțiunea 13)
- `python -m bmwdiag.rezumat <folder_sesiune>`: durata, min/medie/max pe fiecare coloană, numărul de steaguri pe tip, lista marcajelor cu valorile din ±3 s în jurul lor. Fără biblioteci grele.
- Realizat (04.11.2026). `bmwdiag/rezumat.py`, strat subțire peste `sesiuni.py`; doar citire, fără EDIABAS, doar biblioteca standard. Comandă: `python -m bmwdiag.rezumat <folder sau id> [--date <folder>] [--coloane a,b] [--evenimente marcaj|steag|eroare] [--json]`. Afișează în română: stare, profil, condiție, notă, durată, rânduri, cicluri/s, temperatura motorului la început și la sfârșit, steaguri pe tip, min/medie/max cu denumire și unitate din `nume_ro.json` (ce lipsește: nume brut), evenimentele cu tabelul „înainte (t−3 s) / minim (cu momentul) / după (t+3 s) / cădere” pentru rpm, sarcină, pedală, clapetă, tmot, și erorile noi față de start. Implicit se listează marcajele și steagurile; `--evenimente eroare` listează erorile de citire. Id inexistent sau ostil, folder greșit, coloană necunoscută → „Eroare: …” pe stderr și cod de ieșire 2. Fără ANSI.
  - În `sesiuni.py` s-au adăugat `info(id)` (câmpurile din lista de sesiuni pentru o singură sesiune) și `masoara(id, momente, coloane)` (aceleași definiții ca `masoara` din `comparare.js`: înainte = t−3 s, după = t+3 s, minim în [t−3, t+3], toleranță 1,5 s).
  - Argumentul e un id (căutat în folderul de date) sau o cale care conține `\` sau `/` și arată ca `…\sesiuni\<id>`.
  - Teste: `tests/test_rezumat.py` (sesiune FakeSource, id ostil, un rând, fără `sesiune.json`, JSON valid, nimic modificat pe disc, fum pe datele reale).

Etapele 6–9 (vizualizarea sesiunilor în interfața web): secțiunea 13.
Etapele 11–13 (citire live, fără înregistrare, în interfața web): secțiunea 14.

## 11. Analiza datelor

Se face local (notele despre o mașină anume nu sunt în repo). Metoda: sesiuni rece și cald cu aceleași manevre, comparate pe mărimile din profilul `eveniment_rapid`; vezi etapa 9.

## 12. Ce NU faci

- Nu folosi `MSV70`. Nu rula joburi `STEUERN_*`, `*_LOESCHEN`, `*_SCHREIBEN`, `FLASH_*`, `SET_*`, `C_*_SCHREIBEN` etc.
- Nu instala pachete global și nu folosi `C:\Python314`.
- Nu modifica `C:\EDIABAS\Bin\*.INI` fără acord.
- Nu strica `server.py` (îl folosește chatul). Dacă refactorizezi garda, server.py trebuie să importe din `bmwdiag.guard` și să rămână funcțional.
- Nu pune VIN-ul sau date personale în documentele de proiect (repo-ul e public).

## 13. Vizualizare sesiuni în interfața web (adăugat 02.11.2026)

### 13.1 Problema

O sesiune înseamnă acum un folder cu 8 până la 15 fișiere (`sesiune.json`, `coloane.json`, `date_001.csv`…, `evenimente.csv`, `erori_*.json`, `instantaneu_start.json`, `jurnal.txt`). Proprietarul nu poate citi datele normal: CSV-ul are 30+ coloane cu nume scurte, mii de rânduri (până la ~13.000 la 30 de minute) și multe celule goale (grupurile lente), iar JSON-urile sunt pline de câmpuri tehnice (`_TEL_ANTWORT`, `hex:...`). Vrem o pagină în aplicația existentă unde alegi o sesiune dintr-o listă și o vezi într-un format ușor de citit, în română.

Notă: ecranul de înregistrare rămâne fără grafice (secțiunea 0). Vizualizarea sesiunilor lucrează pe date SALVATE, deci graficele sunt permise aici; graficele de citire în timp real stau separat, în pagina Live (secțiunea 14).

### 13.2 Ce arată datele reale (verificat pe sesiunile reale)

- Folderul `bmw-data\sesiuni\` conține sesiunile; folderele vechi `<data>_etapa*_...` din `bmw-data` au alt format (fără `sesiune.json`). Nu se afișează în v1.
- Dimensiuni: de la 1 rând (`instantaneu_complet`, 48 KB) la 13.456 rânduri în 4 segmente (`date_001..004.csv`, ~3,3 MB total). Cel mai mare folder are ~3 MB, deci se poate încărca tot în memorie; nu e nevoie de bază de date.
- Antetul CSV se repetă în fiecare segment. `ciclu` și `t_rel_s` continuă între segmente.
- Coloanele grupurilor lente (`lu1..4` la 5 s, sondele, `regl_*` la 10 s) sunt GOALE în majoritatea rândurilor. În tabel rămân goale, în grafic se unesc punctele existente.
- Valorile au zgomot de virgulă mobilă (`12.151800000000001`): se rotunjesc la afișare (de ex. 4 cifre semnificative), fișierul nu se modifică.
- `evenimente.csv` are tipurile `stare`, `marcaj`, `steag`, `eroare`. Steagurile au text deja explicativ („rpm a scăzut cu 176.2 (870.8 → 694.5) în 1.32 s").
- `erori_start.json`, `erori_stop.json`, `erori_<secunde>.json` (ex. `erori_601.json` = la 10 min) au structura `{t_iso, t_rel_s, fs_lesen:{seturi:[...]}, detalii:{"<nr>": {...}}}`. În `seturi` ultimul element e doar telegrama (`JOB_STATUS`, `_TEL_*`); se sare.
- `instantaneu_start.json` = `{t_iso, joburi:{NUME_JOB:{ok, seturi:[{STAT_X_WERT, STAT_X_EINH, ...}], ...}}}`. Perechile `*_WERT` + `*_EINH` se afișează ca „valoare unitate".
- Sesiunea poate fi: finalizată, în desfășurare (recorder activ), sau întreruptă brutal (fără `sesiune.json` final, ultimul rând CSV posibil trunchiat). Toate trei trebuie să se deschidă.
- `AIF_LESEN` conține VIN-ul. În lista curentă de instantaneu nu apare, dar dacă apare într-un profil, câmpurile cu VIN se maschează implicit în afișare.

### 13.3 Cercetare și decizii

1. Server: rămâne biblioteca standard (`ThreadingHTTPServer`), fără pachete noi (constrângerea Python 32-bit din secțiunea 2). Se adaugă rute `GET`, doar citire.
2. Grafice: se recomandă **uPlot** (MIT, ~50 KB minificat, fără dependențe, desenează ~166.000 de puncte în ~25 ms, suportă zoom, mai multe scale Y, cursor sincronizat între grafice; sursa: github.com/leeoniya/uPlot). Fișierele `uPlot.iife.min.js` și `uPlot.min.css` se pun LOCAL în `bmwdiag/static/vendor/` împreună cu licența, cu versiune fixată. NU se încarcă de pe CDN: laptopul din mașină poate să nu aibă internet. Descărcarea fișierelor e singurul pas cu rețea; dacă nu merge, proprietarul le descarcă manual. Alternativă dacă nu vrem nicio bibliotecă: grafic propriu în SVG/canvas (~200 de linii), mai puțin comod la zoom.
3. Reducerea punctelor: la 13.000 de rânduri × 6–8 coloane trimiterea completă e ~300 KB, deci în v1 se trimite tot. Dacă o sesiune depășește 30.000 de rânduri, serverul face reducere min/max pe găleți (păstrează extremele; LTTB poate netezi exact căderile scurte de turație pe care le căutăm, deci NU se folosește), iar la zoom clientul cere detaliul intervalului.
4. Citire și cache: modul nou `bmwdiag/sesiuni.py` (fără dependențe de EDIABAS), refolosit și de `rezumat` din Etapa 5. Citește cu `csv`, tolerează ultimul rând trunchiat, concatenează segmentele, cache în memorie (3 sesiuni, cheie = folder + mtime-urile fișierelor). Pentru sesiunea activă nu se face cache.
5. Siguranță: id-ul sesiunii trebuie să se potrivească cu `^\d{4}-\d{2}-\d{2}_\d{6}_[\w-]+$` și calea rezolvată trebuie să rămână în `bmw-data\sesiuni`; descărcările brute doar dintr-o listă albă de nume de fișier (`sesiune.json`, `coloane.json`, `date_NNN.csv`, `evenimente.csv`, `erori_*.json`, `instantaneu_start.json`, `jurnal.txt`). Fără scriere, fără ștergere din interfață. Serverul rămâne pe `127.0.0.1`.
6. Vizualizarea nu atinge EDIABAS, deci poate fi folosită și în timpul unei înregistrări (și pentru sesiunea care încă rulează, cu reîmprospătare manuală).

### 13.4 Interfața (în română)

Navigare sus în pagină: „Înregistrare" (pagina actuală) și „Sesiuni". Rută: `/sesiuni.html#<id>` (aceeași pagină, lista și detaliul pe hash, ca să meargă butonul Înapoi).

**Lista sesiunilor** (cea mai nouă prima), tabel cu: data și ora start, profil, condiție (insignă rece/cald/necunoscut), durată, rânduri, cicluri/s, numărul de steaguri (pe tip, la hover), prima parte din notă, motivul opririi, insignă „în desfășurare" sau „întreruptă". Filtre: condiție, profil, text în notă. Sortare după dată. Click pe rând = deschide sesiunea.

**Detaliul sesiunii**, cu file:

1. **Rezumat**: profil, condiție, notă, start/stop, durată, rânduri, segmente, cicluri/s, motiv oprire; temperatura motorului la început și la sfârșit; steaguri pe tip; tabel „min / medie / max" pe fiecare mărime (cu denumire română și unitate); tabel de joburi (apeluri, erori, ms mediu); avertisment dacă au fost erori de citire sau `conexiune_pierduta`.
2. **Grafice**: presetări în română: „Turație" (`rpm`, `rpm_tinta`, `pedala`), „Temperaturi" (`tmot`, `taer`), „Sarcină și cuplu" (`sarcina`, `sarcina_tinta`, `cuplu`, `maf`, `clapeta`), „Amestec" (`fr1`, `fr2`, `te`, `te2`), „Came și avans", „Neregularitate cilindri" (`lu1..4`), „Sonde lambda", „Baterie". Alegere liberă de coloane. Zoom cu mouse, dublu-click = reset, cursor sincronizat între grafice, valorile de sub cursor afișate în legendă. Evenimentele (marcaje, steaguri, erori noi) apar ca linii verticale colorate pe axa timpului. Axa timpului comutabilă între „secunde de la start" și ora locală.
3. **Evenimente**: lista din `evenimente.csv`, cu filtru pe tip. Click pe un eveniment = sare în grafice la fereastra de ±5 s și afișează un mic tabel „înainte / minim / după" pentru `rpm`, `sarcina`, `pedala`, `clapeta`, `tmot` (exact ce trebuie pentru „cade turația la cuplare").
4. **Tabel**: toate rândurile, cu antetul fix, coloane cu denumiri românești (numele scurt în dreapta, la hover), virtualizat (se desenează doar rândurile vizibile), filtru pe interval de timp, „doar rândurile cu marcaj sau steag", grupuri de coloane care se pot ascunde. Valori rotunjite. Celule goale = grup lent necitit în acel ciclu.
5. **Erori**: pentru start, stop și fiecare citire de interval: lista erorilor (număr, text, simptom, stare „bisher nicht aufgetreten", condițiile de mediu: km, turație, temperatura motorului etc. din `detalii`), cu evidențierea celor noi față de start.
6. **Instantaneu la start**: câte o carte pe job (IDENT, ZIF, GEMISCH, FUNKTIONSSTATI, sonde...), cu tabel „mărime — valoare unitate". Câmpurile tehnice (`_TEL_*`, `hex:`, `JOB_STATUS`) ascunse sub „Arată detalii tehnice". Câmpurile cu VIN mascate, buton „Arată".
7. **Jurnal**: `jurnal.txt` ca text, cu căutare.
8. **Fișiere**: lista fișierelor din folder cu dimensiune și link de descărcare (cele din lista albă), plus calea folderului pentru copiere.

Dicționar de denumiri: fișier `bmwdiag/static/nume_ro.json` cu `alias → {eticheta, unitate_afisata, grup}` pentru coloanele din profile (de ex. `rpm` → „Turație", `sarcina` → „Sarcina motorului (umplere)", `fr1` → „Factor lambda banca 1") și `STAT_*` → etichetă pentru instantaneu, luate din secțiunea 4. Ce nu e în dicționar se afișează cu numele brut, fără eroare. Unitățile vin din `coloane.json`, nu se dublează.

### 13.5 API (JSON; GET, plus scrierea fragmentelor salvate)

- `GET /api/sesiuni` → lista (câmpurile din tabelul de listă; calculate din `sesiune.json`; dacă lipsește, din CSV și din `evenimente.csv`).
- `GET /api/sesiuni/<id>` → `sesiune.json` fără `profil_toml`, `coloane.json`, rezumat calculat (min/medie/max), evenimente, erori (parsate, fără câmpuri tehnice), instantaneu (parsat), starea („finalizată" / „în desfășurare" / „întreruptă").
- `GET /api/sesiuni/<id>/date?coloane=rpm,tmot&de_la=<s>&pana_la=<s>&max=<n>` → format pe coloane: `{"t":[...], "rpm":[...], "tmot":[...]}` cu `null` pentru celulele goale; `max` activează reducerea min/max.
- `GET /api/sesiuni/<id>/rezumat?de_la=<s>&pana_la=<s>` → același rezumat ca în `/api/sesiuni/<id>` (min/medie/max, `randuri`, `durata_s`, `tmot_start/stop`), dar doar pe fragment (capete incluse; fără parametri = toată sesiunea). Cu fragment, în plus: `de_la`/`pana_la` (primul și ultimul moment real) și `steaguri` (pe tip, din `evenimente.csv`).
- `GET /api/sesiuni/<id>/fragmente` → fragmentele salvate: `[{id, nume, de_la, pana_la, creat}]`, ordonate după început.
- `POST /api/sesiuni/<id>/fragmente` cu `{nume, de_la, pana_la}` → 201 și lista actualizată. 400 la nume gol sau mai lung de 60 de caractere, capete nenumerice, `de_la < 0` sau `de_la >= pana_la`, ori peste 50 de fragmente pe sesiune. `POST /api/sesiuni/<id>/fragmente/<fid>/sterge` → lista actualizată (404 dacă nu există). Fragmentele se scriu în `bmw-data\fragmente\<id>.json` (scriere atomică), NU în folderul sesiunii: fișierele sesiunii rămân neatinse. Sunt singura scriere a acestor rute.
- `GET /api/sesiuni/<id>/rand?t=<s>` → rândul cel mai apropiat de momentul `t` (pentru cardul „la acest moment").
- `GET /api/sesiuni/<id>/fisier/<nume>` → descărcare din lista albă.
- `GET /api/sesiuni/<id>/jurnal` → text.
- Ruta statică nouă: `/sesiuni.html`, `/sesiuni.js`, `/vendor/*` (doar fișierele cunoscute, la fel ca `FISIERE_STATICE`).

### 13.6 Etape și criterii de acceptare

Etapa 6 – Citirea și API-ul (fără interfață)
- `bmwdiag/sesiuni.py`: `lista()`, `incarca(id)`, `date(id, coloane, ...)`, `rezumat(id)`.
- Teste în `tests/test_sesiuni.py`: sesiune generată cu `FakeSource` (un segment și mai multe), `sesiune.json` lipsă, ultimul rând CSV trunchiat, sesiune cu un singur rând, id-uri ostile (`..\..`, `x/../y`, nume cu `:`) → 400/404, fișier în afara listei albe → 404, celule goale → `null`.
- Test de fum pe datele reale din `bmw-data\sesiuni`, sărit automat dacă folderul lipsește.
- Criteriu: toate sesiunile reale se încarcă; o sesiune de ~13.500 de rânduri; răspunsul la `/api/sesiuni/<id>/date` pentru 6 coloane sub 500 KB și sub 200 ms în afara primei citiri.

Etapa 7 – Pagina „Sesiuni": listă, rezumat, evenimente, erori, instantaneu, jurnal, fișiere (fără grafice)
- Criteriu: se poate alege oricare din cele 9 sesiuni, iar proprietarul vede în română durata, steagurile, marcajele, erorile și instantaneul fără să deschidă un fișier. Merge cu Înapoi/Înainte și cu reîncărcarea paginii. Cu o înregistrare activă, lista arată sesiunea ca „în desfășurare".
- Realizat (04.11.2026). `bmwdiag/static/sesiuni.html` + `sesiuni.js`, rute statice `/sesiuni.html`, `/sesiuni.js`, `/nume_ro.json`; navigare „Înregistrare / Sesiuni" în ambele pagini. Detalii de implementare:
  - Rută: `#<id>` (lista → detaliu) și `#<id>/<tab>` (tab: `rezumat`, `evenimente`, `erori`, `instantaneu`, `jurnal`, `fisiere`). Schimbarea filei folosește `replaceState` (Înapoi duce la listă, nu prin toate filele); reîncărcarea păstrează sesiunea și fila.
  - `nume_ro.json` are cheile: `coloane` (alias → `eticheta`, `unitate_afisata`, `grup`), `stat` (`STAT_*`/`ID_*`/`ZIF_*` → etichetă), `joburi` (job → denumire), `steaguri` (tip steag → denumire), `unitati` (unitatea brută → afișată, ex. `min-1` → `rpm`), `erori_detalii`. Ce lipsește se afișează cu numele brut. Un test verifică că fiecare alias și fiecare rezultat din `profiles/*.toml` are denumire.
  - „Detalii tehnice" la instantaneu: serverul scoate deja `_TEL_*`, `JOB_STATUS` și valorile `hex:`; butonul de pe fiecare carte arată numele brut al câmpului, starea jobului și numărul de seturi. Câmpurile cu VIN (cheie cu `VIN`/`FGNR`/`FAHRGEST` sau valoare de 17 caractere de tip VIN) sunt mascate cu buton „Arată".
  - Pe ecran îngust (≤ 640 px) lista devine cartele (câte un bloc pe sesiune).
  - Corecție în `sesiuni.py`: pentru o sesiune fără `stop` (activă sau întreruptă), durata și ciclurile/s se calculează din date, deoarece `sesiune.json` are statistici zero până la oprire.

Etapa 8 – Grafice și tabel
- uPlot local (`static/vendor/`, licența inclusă), presetările din 13.4, linii verticale pentru evenimente, zoom, sincronizare cursor, tabelul virtualizat.
- Criteriu: sesiunea de 13.456 de rânduri se afișează fluid (fără blocarea paginii) iar căderea de turație de la un steag `cadere_la_cuplare` se vede clar când dai click pe eveniment. Pagina funcționează fără internet.

- Realizat (04.11.2026). Fișiere: `static/sesiuni_date.js` (grafice + tabel, se încarcă înaintea lui `sesiuni.js`), `static/vendor/` (uPlot 1.6.31, `LICENSE-uPlot.txt`, `VERSIUNE.txt`), rute statice `/sesiuni_date.js` și `/vendor/{uPlot.iife.min.js,uPlot.min.css,LICENSE-uPlot.txt}`. Detalii:
  - Filele noi: „Grafice” (după Rezumat) și „Tabel” (după Evenimente). Presetările din 13.4 plus „Viteză”; „Grafic liber” cu până la 8 coloane. O axă Y pe unitate (`% pedală`, `% clapetă` și `%` împart axa „%”).
  - Vederea de ansamblu cere `/date?...&max=5000`; la zoom (și după 220 ms) fiecare grafic cere detaliul ferestrei (+25% margine, `max=3000`). Zoom-ul și cursorul sunt sincronizate între grafice; dublu-click sau „Vedere de ansamblu” resetează; butoanele −, +, ←, → ajută pe telefon. Valoarea nulă din legendă arată ultima valoare citită, cu „~”.
  - Linii verticale: marcaje (verde, întrerupt), steaguri (galben), erori noi (roșu, întrerupt); evenimentul ales e accentuat. Hover lângă linie afișează textul evenimentului.
  - Evenimente: buton „Vezi în grafice” (și click pe rând) → fereastra ±5 s și tabelul „înainte (t−3 s) / minim (cu momentul) / după (t+3 s) / minim − înainte” pentru rpm, sarcină, pedală, clapetă, tmot.
  - Tabel: rânduri desenate doar pe cele vizibile (~25–40 în DOM), antet și primele două coloane fixe, filtru de interval (secunde sau m:ss), „doar rândurile cu marcaj sau steag” (verde/galben), grupuri de coloane ascunse din „Grupuri de coloane afișate”.
  - API: `/date` acceptă acum și coloanele text `marcaj`, `steaguri`, `t_iso` (la reducere nu intră în calculul extremelor).
  - Ora locală pe axă: decalajul se ia din `/rand?t=0`.
  - Temă deschisă/închisă prin variabilele `--serie-N` și `--ev-*` din `style.css`; graficele se reconstruiesc la schimbarea temei.

Etapa 9 – Comparare rece / cald
- Alegi două sesiuni și le suprapui pe același grafic, aliniate la un eveniment ales din fiecare (de ex. primul „Cuplez ambreiajul" sau un steag `cadere_la_cuplare`), cu t = 0 la eveniment și fereastră de ±5 s. Tabel „cădere de turație, sarcină, cuplu, clapetă" la fiecare cuplare, rece vs cald. Aceasta e legătura directă cu scopul din secțiunea 11.

- Realizat (04.11.2026). Pagină separată `/comparare.html` (navigare „Înregistrare / Sesiuni / Comparare” în toate paginile), `static/comparare.js`, rute statice `/comparare.html` și `/comparare.js`. Fără endpoint nou: pentru fiecare sesiune se citesc `/api/sesiuni/<id>` (evenimente) și `/date` cu 11 coloane complete (rpm, sarcină, cuplu, clapetă, pedală, tmot, viteză, maf, avans, sarcina_tinta, rpm_tinta), iar fereastra și tabelul se calculează în browser. Detalii:
  - Alegeri: sesiunea A și B, tipul de eveniment comparat (steag după nume, marcaj după text, erori noi, „toate”) și evenimentul de aliniere din fiecare sesiune (implicit primul cu motorul deja pornit). Implicit: cea mai mare sesiune rece ca A și cea mai mare caldă ca B.
  - Grafic: un grafic uPlot pe mărime (bife), serii „A: rece 13:53” și „B: cald 15:05”, axa x = secunde față de eveniment, fereastră ±3 / 5 / 10 / 20 s, linie la t = 0 și la ±3 s (momentele „înainte” și „după”), zoom cu mouse (sincronizat), dublu-click sau „Fereastra întreagă” = reset, legendă cu valori sub cursor.
  - Tabel: „Rezumat pe sesiune” (înainte / minim medii, cădere medie și mediană, B − A) și câte un tabel pe sesiune cu înainte / minim / după / cădere pentru rpm, sarcină, cuplu, clapetă la fiecare eveniment; click pe rând = aliniază graficul la acel eveniment. Definiții: înainte = t−3 s, după = t+3 s, minim în [t−3, t+3], cădere = înainte − minim.
  - Starea e în hash (`#a=&b=&c=&ea=&eb=&m=&w=`): schimbarea sesiunii creează intrare în istoric (Înapoi/Înainte), restul folosește `replaceState`; reîncărcarea păstrează totul. Fără internet, fără scriere.
  - Test: `test_pagina_comparare_fara_cdn_si_navigare` în `tests/test_webapp.py`.

Etapa 5 (rezumat în consolă) e făcută pe `bmwdiag/sesiuni.py`, nu separat, ca să nu existe două implementări.

### 13.7 Reguli pentru implementare

- Nu se modifică fișierele unei sesiuni existente. Vizualizarea e strict de citire.
- Nu se schimbă formatul fișierelor scrise de `recorder.py` fără acord; dacă lipsește ceva util (de ex. `t_iso` în `sesiune.json` pentru fiecare segment), se notează aici și se întreabă.
- Fără pachete noi Python. Singurul activ extern: uPlot, local, versiune fixată.
- Textele din interfață în română. Date în formatul `ZZ.LL.AAAA HH:MM`.
- După fiecare etapă: actualizează `BMW_CONTEXT.md` (de ex. dimensiunile reale, timpii de încărcare) și rulează testele existente (nu strica `server.py` și înregistrarea).

### 13.8 Întrebări deschise (decide proprietarul; până atunci se aplică valoarea implicită)

1. Graficele în v1: da (implicit) sau doar tabele?
2. Comparația rece/cald (Etapa 9): se face după ce merge vizualizarea unei sesiuni (implicit).
3. Notă ulterioară pe o sesiune (de ex. „aici am apăsat gazul în podea"): în v1 nu; dacă se vrea, se salvează într-un fișier separat `note_ulterioare.txt`, fără a atinge `sesiune.json`.
4. Folderele vechi `<data>_etapa*` din `bmw-data`: nu se afișează în v1.

Etapa 10 – Fragment global (slider) și fragmente salvate
- La citirea unei sesiuni alegi un interval `[de, până]` și toată pagina arată datele doar pentru el.

- Realizat (04.11.2026). `static/fragment.js` (încărcat după `sesiuni_date.js`, rută statică `/fragment.js`), bara `#bara-fragment` în `sesiuni.html`, stiluri `.fragment` / `.fr-*` în `style.css`. Detalii:
  - Bara „Fragment” stă deasupra filelor și rămâne la schimbarea lor. Slider dublu peste un minigrafic (turație, altfel viteză sau temperatura motorului) cu marcajele evenimentelor. Gesturi: tragi pe minigrafic = fragment nou; tragi un mâner = ajustezi un capăt; tragi zona = o muți; dublu-click sau „Toată sesiunea” = resetare. Mânerele sunt `role="slider"` și merg cu tastatura (←/→ 1 s, Shift 10 s, Ctrl 0,1 s, Home/End). Funcționează și cu degetul (`touch-action: none`). Mai sunt câmpurile „De la” / „Până la” (secunde sau m:ss) și lista „În jurul unui eveniment (±5 s)”.
  - Se aplică la eliberare (nu la fiecare mișcare), cu `replaceState`. Starea e în hash: `#<id>/<tab>?de=<s>&pana=<s>`; reîncărcarea și linkul o păstrează. Un fragment din link în afara sesiunii se aduce în limite. Fără parametri înseamnă toată sesiunea.
  - Efectul pe file: **Rezumat** se recalculează pe server (`/rezumat?de_la&pana_la`; „Joburi citite” și avertismentele rămân pe toată sesiunea, cu notă); **Grafice** cer datele fragmentului la rezoluție completă (max 5000 de puncte doar pe fragment), iar „Vedere de ansamblu”, −, +, ← și → rămân în fragment; **Tabel** aplică filtrul „De la / Până la” în interiorul fragmentului; **Evenimente** și **Erori** arată doar ce cade în fragment (cu numărul celor ascunse; „NOU” la erori rămâne față de citirea de la start). „Vezi în grafice” pe un eveniment din afara fragmentului renunță la fragment.
  - Fragmente salvate cu nume (butonul „Salvează fragmentul”, chip-uri cu aplicare și ștergere cu confirmare), pe sesiune. Se vor putea folosi mai departe la comparare (încă nu).
  - Teste: `test_rezumat_pe_fragment`, `test_fragmente_salvate`, `test_fragmente_date_invalide`, `test_fragmente_fisier_stricat` în `tests/test_sesiuni.py`; `test_fragment_api_si_pagina` în `tests/test_webapp.py`. Verificat în browser pe două sesiuni reale (rece 12.040 rânduri / cald, copiate într-un folder temporar): tragere cu mouse real, tastatură, reîncărcare, salvare/aplicare/ștergere, toate filele, ecran de 375 px (fără scroll orizontal), temă deschisă și închisă.

## 14. Citire live, fără înregistrare (implementat 05.11.2026)

Scop: să vezi valorile și graficele în timp ce mașina merge, FĂRĂ să scrii nimic pe disc. „Live" e un mod de citire separat de înregistrare: nicio sesiune nouă, niciun CSV, niciun `sesiune.json`, niciun instantaneu, nicio citire automată de erori. Datele stau doar în memorie și dispar la următorul Start; singura scriere posibilă e „Salvează", cerută explicit (14.3, Etapa 13). Pagina Live e singura cu grafice în timp real; ecranul de înregistrare rămâne fără grafice (secțiunea 0).

Principii (nu se negociază):
- DOAR CITIRE, prin aceeași gardă (`bmwdiag/guard.py`) și aceleași joburi ca la înregistrare. Nicio scriere pe mașină.
- EDIABAS = o singură sesiune pe port: live, înregistrarea și serverul MCP din chat nu citesc în același timp. Aplicația ține un singur recorder activ; cât rulează live, Start de înregistrare, Start live și citirea de erori sunt refuzate cu 409 și mesaj în română (și invers, live e refuzat cât se înregistrează). Blocarea `logger.lock` e pe procesul `bmwdiag.webapp`, deci se aplică la fel; avertismentul despre MCP apare și pe pagina Live.
- Citirea live se oprește singură după 60 s fără nicio cerere `GET /api/live` (browser închis, calculator adormit) și eliberează portul; Stop o oprește oricând.
- Nu scrie nimic în `bmw-data`; jurnalul din interfață (conectare, reconectări, marcaje, steaguri) rămâne în memorie.
- Aceeași reconectare automată, aceleași steaguri și același tratament al erorilor de citire ca la înregistrare: o singură buclă de citit mașina (`Recorder`).
- Fără internet, fără CDN (uPlot local). Fără mașină se testează cu `FakeSource` și `ReplaySource`. Interfața și mesajele sunt în română.

### 14.1 Ce arată pagina `/live.html`

- Navigare „Înregistrare / Sesiuni / Live / Comparare" în toate paginile. Alegerea profilului (din `profiles/`), butoane Start live / Stop și bannerul „nu se salvează nimic".
- Stare: etichetă (oprit / pornește / citește live / reconectare / eroare), „ultima citire reușită acum X s" (verde sub 2 s, galben 2–5 s, roșu peste 5 s), cicluri/s, timp scurs, erori de citire, număr de steaguri.
- Cartele cu valoarea curentă (turație, pedală, sarcină, cuplu, clapetă, temperatura motorului, viteză, tensiune, MAF, avans; doar cele existente în profil), cu etichete și unități din `nume_ro.json`. O mărime dintr-un grup lent, fără valoare în ultimul ciclu, se arată estompat cu ultima valoare citită.
- Grafice cu presetările din Etapa 8 și ferestre de 30 s / 2 min / 10 min (până se umple fereastra, graficul crește spre dreapta, apoi derulează). „Îngheață graficele" păstrează intervalul și datele afișate cât timp citirea continuă. Linii verticale pentru marcaje (verde, întrerupt), steaguri (galben) și erori.
- Marcaje: butoanele și tastele din profil; apar ca linii pe grafic, doar în memorie.
- „După citire": „Salvează" și „Începe înregistrarea" (14.3).

### 14.2 Cum se citește și cum ajung datele în pagină

- **Cititor live:** `Recorder(profil, sursa, scrie=False, inactiv_s=60)`: aceeași buclă ca la înregistrare. În modul live nu se creează folder, CSV, `sesiune.json`, `coloane.json`, instantaneu, citiri de erori, segmente, `evenimente.csv` sau `jurnal.txt`. Limitele profilului (`durata_max_minute`, `cicluri_max`) se ignoră. Starea e `live`, iar `stare()` are câmpul `mod` (`live` / `inregistrare`). Anti-somnul rămâne activ cât timp se citește.
- **Buffer în memorie:** `deque(maxlen=6000)` de rânduri cu valori numerice (≈15 min la 7 cicluri/s; la profile mai rapide acoperă mai puțin) și până la 500 de evenimente (marcaj, steag, eroare), umplute în firul cititorului sub un lock scurt. Rămâne disponibil și după oprire, până la următorul Start.
- **API (JSON):**
  - `POST /api/live/start {profil}` și `POST /api/live/stop` (la fel ca `/api/stop`, dar fără `folder`).
  - `GET /api/live?de_la_ciclu=N&de_la_ev=M&coloane=a,b` → rândurile cu `ciclu > N`, pe coloane, ca la `/date`: `t`, `ciclu`, câte un alias (număr sau `null`), `marcaj`, `steaguri`; plus `ciclu_ultim`, `reset`, `evenimente` (cu `nr > M`, `{nr, t, tip, detalii}`), `ev_ultim`, `unitati`, `aliasuri`, `profil`, `activ`, `stare`, `mod`, `timp_s`, `cicluri_pe_s`, `ultima_reusita_s`, `erori`, `steaguri_total`, `motiv_oprire`. Fără `coloane` vin toate coloanele profilului. `reset=true` înseamnă că cursorul a ieșit din buffer sau s-au cerut peste 5000 de rânduri (clientul își reface datele). Fiecare apel reînnoiește temporizatorul de inactivitate. Fără nicio citire live: 200 cu `stare: "oprit"` și liste goale. 400 la parametri invalizi sau coloană necunoscută; 409 dacă rulează o înregistrare.
  - `POST /api/live/salveaza {secunde, conditie, nota}` (14.3, Etapa 13).
- **Transport:** interogare periodică la 0,7 s cât citește (2,5 s când e oprită). Fluxul SSE nu a fost necesar.

### 14.3 Etape

Etapa 11 – Cititor live și API
- Modul de citire fără scriere, cu buffer circular, blocare comună cu înregistrarea, oprire automată la inactivitate și rutele din 14.2.
- Criteriu: cu `fake`, `/api/live` întoarce rânduri noi la fiecare cerere, fără goluri și fără dubluri între cereri consecutive; după o rulare live, `bmw-data` nu conține fișiere noi; Start de înregistrare în timpul live (și invers) e refuzat clar; după 60 s fără cereri citirea se oprește și portul e liber; testele existente și cele noi trec.
- Realizat (05.11.2026). Decizia din 14.2: `Recorder` cu parametrul `scrie=False` (o singură bucla de citire; `scrie=True` rămâne implicit și neschimbat). Detalii:
  - `bmwdiag/recorder.py`: `Recorder(..., scrie=False, inactiv_s=60)`. În modul live `_pregateste` doar pornește sursa; nu există folder, CSV, `sesiune.json`, `coloane.json`, instantaneu, citiri de erori, segmente, `jurnal.txt` sau `evenimente.csv`. Limitele profilului (`durata_max_minute`, `cicluri_max`) se ignoră. Bufferul e un `deque(maxlen=6000)` de rânduri cu valori numerice (≈15 min la 7 cicluri/s), plus până la 500 de evenimente (marcaj, steag, eroare) în memorie. `_incheie` are o ramură separată pentru live (oprește sursa, nu scrie nimic). Starea nouă `live`, iar `stare()` are câmpul `mod` (`live` / `inregistrare`).
  - `date_live(de_la_ciclu, coloane, de_la_ev)` întoarce rândurile cu `ciclu > de_la_ciclu` pe coloane (`t`, `ciclu`, un alias pe coloană, `null` pentru celule goale sau netextuale), `reset=true` dacă cursorul a ieșit din buffer sau s-au cerut peste 5000 de rânduri, evenimentele noi, `unitati`, `stare`, `cicluri_pe_s`, `ultima_reusita_s`. Fiecare apel reînnoiește temporizatorul de inactivitate; după `inactiv_s` fără apel citirea se oprește singură cu motivul „inactivitate”.
  - `bmwdiag/webapp.py`: `Aplicatie.start(..., live=True)` / `start_live`; același slot `recorder` ca la înregistrare, deci excluderea e automată (409 cu mesaj care spune ce rulează). Citirea erorilor în timpul live dă 409. `GET /api/live` (după oprire întoarce bufferul rămas, cu `activ=false`), `POST /api/live/start`, `POST /api/live/stop` și `POST /api/live/salveaza`; formatul complet e în 14.2.
  - Teste: `tests/test_live.py` (nimic pe disc, cursor fără goluri sau dubluri, reset, valori numerice, oprire la inactivitate, marcaje și ignorarea `cicluri_max`, export) și `test_live_api_fara_scriere_si_excludere`, `test_live_se_opreste_singur_fara_cereri` în `tests/test_webapp.py`.

Etapa 12 – Pagina `/live.html`
- Cartele, grafic derulant cu uPlot local, îngheț, marcaje și steaguri pe ecran, navigare între pagini.
- Criteriu: cu `fake`, valorile se mișcă și graficul derulează 30 de minute fără acumulare de memorie; închiderea paginii oprește citirea după timeout, iar redeschiderea nu pornește nimic singură; funcționează fără internet și pe ecran îngust (375 px); verificat în browser.
- Realizat (05.11.2026). Fișiere: `static/live.html`, `static/live.js`, rute statice `/live.html` și `/live.js`, link „Live” în navigarea tuturor paginilor, stiluri `.cv` / `.cartele-live` în `style.css`. Detalii:
  - Alegere profil, Start live / Stop, banner „nu se salvează nimic” și avertismentul despre MCP. Interogare la 0,7 s cât citește (2,5 s când e oprită). Reîncărcarea paginii reia din bufferul serverului (nu pornește nimic singură). Dacă rulează o înregistrare, pagina arată mesajul 409.
  - Cartele cu valoarea curentă (turație, pedală, sarcină, cuplu, clapetă, temperatura motorului, viteză, tensiune, MAF, avans), cu etichete și unități din `nume_ro.json`; un grup lent (fără valoare în ultimul ciclu) se arată estompat cu ultima valoare citită. Indicator de prospețime verde / galben / roșu, cicluri/s, erori, steaguri.
  - Grafice cu presetările din Etapa 8, fereastră de 30 s / 2 min / 10 min (până se umple, graficul crește spre dreapta), linii verticale pentru marcaje și steaguri. „Îngheață graficele” păstrează intervalul și datele (copii) cât citirea continuă. Marcaje cu butoane și tastele din profil. Clientul păstrează ~11 min și taie în blocuri.
  - În ecranul Înregistrare, o citire live apare ca „citire live (nu se salvează)”, iar Start rămâne dezactivat.
  - Verificat în browser cu `fake` (server de test pe alt port, folder de date temporar): Start, valori și grafice în mișcare, reîncărcare cu reluare, tasta 1 ca marcaj, îngheț, ferestre, oprire automată după 60 s fără cereri, 375 px fără scroll orizontal, nimic scris în folderul de date. Neverificat încă: rulare de 30 de minute și măsurarea ciclurilor/s live față de înregistrare pe mașina reală.

Etapa 13 – Din live în înregistrare și salvare explicită
- „Începe înregistrarea" oprește live și pornește înregistrarea cu același profil; „Salvează ultimele N secunde" exportă bufferul ca sesiune, doar la cerere.
- Criteriu: trecerea din live în înregistrare nu strică datele și nu lasă portul blocat; sesiunea salvată se deschide în pagina Sesiuni.
- Realizat (05.11.2026). Decizia din 14.4: la „Începe înregistrarea" datele deja citite NU intră în înregistrare (se oprește live, apoi pornește o înregistrare nouă, cu o scurtă întrerupere la reconectare; confirmare în pagină); cine vrea să le păstreze le salvează întâi. Detalii:
  - `Recorder.exporta_buffer(secunde, dir_date, conditie, nota)` și `POST /api/live/salveaza {secunde, conditie, nota}`: scrie o sesiune normală (`date_001.csv` cu `t_rel_s` de la 0, `evenimente.csv` cu marcajele și steagurile din fereastră, `coloane.json`, `sesiune.json` cu `origine: "live"` și `motiv_oprire: "exportat din citirea live"`). Merge și după oprirea citirii, cât timp recorderul există (până la următorul Start). 400 la secunde nepozitive, condiție invalidă sau buffer gol; 409 dacă nu e o citire live. Este singura scriere a modului live.
  - În pagină: secțiunea „După citire” cu „Salvează” (link „Deschide sesiunea”) și „Oprește live și începe înregistrarea” (apoi trece la ecranul Înregistrare). Sesiunea salvată se deschide în Sesiuni cu grafice, rezumat și slider de fragment ca orice sesiune.
  - Teste: `test_exporta_buffer_ca_sesiune`, `test_export_doar_din_live_si_buffer_gol` și partea de salvare din testul API.

### 14.4 Decizii luate la implementare

- Cartelele implicite sunt o listă fixă în `live.js` (cele din 14.1, doar cele existente în profil); nu s-a adăugat un câmp nou în TOML.
- Bufferul are 6000 de rânduri (≈15 min la 7 cicluri/s); la profile mai rapide acoperă mai puțin timp.
- „Începe înregistrarea” pornește de la zero (vezi Etapa 13); modul „doar live” fără scriere este chiar modul implicit al paginii Live.
