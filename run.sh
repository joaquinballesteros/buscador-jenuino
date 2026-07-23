#!/usr/bin/env bash
# Arranca la web usando SIEMPRE el entorno virtual del proyecto,
# esté o no activado. Uso:  ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "No existe .venv. Créalo con:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

exec .venv/bin/python server.py
