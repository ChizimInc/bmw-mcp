@echo off
rem Porneste loggerul cu interfata web si deschide browserul.
rem   start_logger.bat         -> masina reala (EDIABAS)
rem   start_logger.bat fake    -> date simulate, pentru proba acasa
rem Cat timp inregistrezi, nu folosi serverul MCP din chat.
cd /d %~dp0
set SURSA=ediabas
if /i "%1"=="fake" set SURSA=fake
.venv\Scripts\python.exe -m bmwdiag.webapp --sursa %SURSA% --deschide
pause
