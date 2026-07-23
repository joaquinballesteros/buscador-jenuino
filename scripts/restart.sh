#!/usr/bin/env bash
# Reinicia el servidor para recargar config.json. Uso:  ./scripts/restart.sh
set -euo pipefail
cd "$(dirname "$0")"
./stop.sh
exec ./run.sh
