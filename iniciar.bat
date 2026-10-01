@echo off
REM Inicia o Nossos Gastos (Windows). Na primeira vez, instala tudo sozinho.
cd /d "%~dp0"
if not exist .venv (
  echo Preparando o ambiente, so na primeira vez...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -r requirements.txt
)
if not exist .env (
  copy .env.example .env >nul
  echo Criei o arquivo .env: abra-o e cole sua ANTHROPIC_API_KEY.
)
.venv\Scripts\python run.py
pause
