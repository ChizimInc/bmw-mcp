@echo off
rem cryptography nu are pachet precompilat pentru Python 32-bit, iar serverul
rem stdio nu il foloseste. Instalam mcp fara dependente si adaugam restul manual.
set PY=%LOCALAPPDATA%\Programs\Python\Python313-32\python.exe
cd /d %~dp0
if not exist .venv\Scripts\python.exe "%PY%" -m venv .venv
set VPY=.venv\Scripts\python.exe

echo ===== 1/4 PyDIABAS =====
%VPY% -m pip install --upgrade pip
%VPY% -m pip install pydiabas

echo.
echo ===== 2/4 Test TMODE (fara masina) =====
%VPY% test_tmode.py

echo.
echo ===== 3/4 MCP (fara cryptography) =====
%VPY% -m pip install "mcp<2" --no-deps
%VPY% -m pip install anyio httpx httpx-sse jsonschema pydantic pydantic-settings pyjwt python-multipart pywin32 sse-starlette starlette typing-extensions typing-inspection uvicorn

echo.
echo ===== 4/4 Verificare server =====
%VPY% -c "import server; print('server.py se importa OK')"
%VPY% -m pip check

echo.
pause
