@echo off
rem Meu Vendedor: prepara o ambiente na primeira vez e abre o painel.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente Python...
  python -m venv .venv || goto erro
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto erro
".venv\Scripts\python.exe" -m app
goto fim
:erro
echo.
echo Algo deu errado. Confira se o Python 3.10 ou mais novo esta instalado (python --version).
pause
:fim
