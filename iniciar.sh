#!/usr/bin/env bash
# Inicia o Nossos Gastos (macOS / Linux). Na primeira vez, instala tudo sozinho.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Preparando o ambiente (só na primeira vez)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Criei o arquivo .env: abra-o e cole sua ANTHROPIC_API_KEY."
fi
exec .venv/bin/python run.py
