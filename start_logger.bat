@echo off
rem Porneste loggerul cu interfata web si deschide browserul.
rem   start_logger.bat               -> masina reala (EDIABAS), doar pe laptop
rem   start_logger.bat fake          -> date simulate, pentru proba acasa
rem   start_logger.bat retea         -> accesibil si de pe telefon (acelasi wifi), cu cod de acces
rem   start_logger.bat fake retea    -> ambele
rem Cat timp inregistrezi, nu folosi serverul MCP din chat.
cd /d %~dp0
set SURSA=ediabas
set HOST=127.0.0.1
for %%A in (%*) do (
  if /i "%%A"=="fake" set SURSA=fake
  if /i "%%A"=="retea" set HOST=0.0.0.0
)
.venv\Scripts\python.exe -m bmwdiag.webapp --sursa %SURSA% --host %HOST% --deschide
pause
