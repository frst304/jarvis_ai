#!/usr/bin/env bash
# Lancement JARVIS (macOS / Linux)
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Installation de JARVIS (premiere fois)..."
  python3 -m venv .venv && .venv/bin/pip install --upgrade pip >/dev/null && .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
exec .venv/bin/python run.py "$@"
