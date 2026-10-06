#!/usr/bin/env bash
# Inicia o Nossos Gastos (macOS / Linux). Na primeira vez, instala tudo sozinho.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  # O python3 que vem com o macOS é o 3.9, antigo demais: procura um 3.10+.
  PY=""
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PY="$cand"
      break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Precisa do Python 3.10 ou mais novo. Baixe em https://www.python.org/downloads/ e rode de novo."
    exit 1
  fi
  echo "Preparando o ambiente com $PY (só na primeira vez)..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
fi

# Rápido quando já está tudo instalado; também conserta uma instalação que falhou no meio.
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Criei o arquivo .env com as configurações opcionais (senha do app, porta...)."
fi
exec .venv/bin/python run.py
