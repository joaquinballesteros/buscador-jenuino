#!/usr/bin/env bash
# Para el servidor del Buscador JENUINO (el que arranca run.sh).
# Uso:  ./scripts/stop.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8000}"
killed=0

# 1) por puerto (lo más fiable): quien escuche en el 8000
pids=$(lsof -ti tcp:"$PORT" -s tcp:LISTEN 2>/dev/null || true)
# 2) por si acaso, por nombre de proceso
pids="$pids $(pgrep -f 'server:app' 2>/dev/null || true) $(pgrep -f '[s]erver.py' 2>/dev/null || true)"

pids=$(echo "$pids" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u)

if [[ -z "$pids" ]]; then
  echo "No hay ningún servidor escuchando en el puerto $PORT."
  exit 0
fi

for pid in $pids; do
  if kill "$pid" 2>/dev/null; then
    echo "Parado el proceso $pid."
    killed=1
  fi
done

# espera a que suelte el puerto; si sigue vivo, fuerza
for _ in 1 2 3 4 5; do
  sleep 0.3
  lsof -ti tcp:"$PORT" -s tcp:LISTEN >/dev/null 2>&1 || break
done
remaining=$(lsof -ti tcp:"$PORT" -s tcp:LISTEN 2>/dev/null || true)
if [[ -n "$remaining" ]]; then
  echo "No terminó por las buenas; forzando (kill -9)…"
  kill -9 $remaining 2>/dev/null || true
fi

[[ "$killed" == 1 ]] && echo "Servidor detenido." || echo "Nada que parar."
