@echo off
REM Inicia o Nossos Gastos (Windows). Na primeira vez, instala tudo sozinho.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
  if errorlevel 1 (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if errorlevel 1 (
      echo Precisa do Python 3.10 ou mais novo. Baixe em https://www.python.org/downloads/
      echo Na instalacao, marque a opcao "Add python.exe to PATH".
      pause
      exit /b 1
    )
    echo Preparando o ambiente, so na primeira vez...
    python -m venv .venv
  ) else (
    echo Preparando o ambiente, so na primeira vez...
    py -3 -m venv .venv
  )
  .venv\Scripts\python -m pip install --quiet --upgrade pip
)

REM Rapido quando ja esta tudo instalado; tambem conserta uma instalacao que falhou no meio.
.venv\Scripts\python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Nao consegui instalar as dependencias. Confira a internet e rode de novo.
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo Criei o arquivo .env com as configuracoes opcionais: senha do app, porta etc.
)
.venv\Scripts\python run.py
pause
