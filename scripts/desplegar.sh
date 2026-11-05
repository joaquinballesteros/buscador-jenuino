#!/usr/bin/env bash
# Copia al servidor (por defecto, la máquina virtual de la UMA) lo necesario
# para servir búsquedas, SIN git: compara huellas SHA-256 a ambos lados y envía
# solo lo que ha cambiado, como un tar por SSH. No hace falta rsync.
#
#   ./scripts/desplegar.sh                  # envía lo que haya cambiado
#   ./scripts/desplegar.sh --simular        # solo lista lo que enviaría
#   ./scripts/desplegar.sh --traer-juicios  # trae evaluacion/juicios/ del servidor
#
# Nunca envía evaluacion/juicios/ (los juicios se escriben en el servidor) ni
# .env, pdf/, fichas/, .venv/ o servidor_uma/. No borra en el servidor lo que
# se borre aquí.
#
# Destino configurable por entorno: DESTINO (root@jenui.uma.es), PUERTO (22360),
# RUTA (/home/jenui/buscador-jenuino), USUARIO_APP (jenui). La autenticación es
# la de tu ssh (agente o ~/.ssh/config), p. ej.:
#   SSH_AUTH_SOCK=/run/user/1000/ssh-jenui.sock ./scripts/desplegar.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DESTINO="${DESTINO:-root@jenui.uma.es}"
PUERTO="${PUERTO:-22360}"
RUTA="${RUTA:-/home/jenui/buscador-jenuino}"
USUARIO_APP="${USUARIO_APP:-jenui}"
SSH=(ssh -p "$PUERTO" -o BatchMode=yes -o ServerAliveInterval=30 "$DESTINO")

MODO=enviar
case "${1:-}" in
  "") ;;
  --simular) MODO=simular ;;
  --traer-juicios) MODO=traer ;;
  *) echo "Opción desconocida: $1"; exit 1 ;;
esac

if [[ $MODO == traer ]]; then
  echo "Trayendo evaluacion/juicios/ de $DESTINO (sobrescribe las copias locales de esos evaluadores)…"
  "${SSH[@]}" "cd '$RUTA' && [ -d evaluacion/juicios ] && tar cf - evaluacion/juicios || true" | tar xvf - 2>/dev/null \
    || echo "El servidor aún no tiene juicios."
  exit 0
fi

# --- lo que necesita el servidor para buscar ---
payload() {
  find jenui scripts static prompts docs -type f ! -path '*/__pycache__/*' ! -name '*.pyc'
  for f in config.json requirements.txt README.md \
           data/corpus.jsonl data/fulltext_vectors.npy data/fulltext_meta.json \
           data/index_manifest.json data/entity_aliases.json \
           data/concept_vectors.npz data/entity_name_vectors.npz \
           rag_storage/graph_chunk_entity_relation.graphml rag_storage/kv_store_text_chunks.json \
           evaluacion/consultas.csv evaluacion/candidatos.json; do
    [[ -f $f ]] && echo "$f"
  done
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
payload | sort > "$tmp/lista"
xargs -d '\n' sha256sum < "$tmp/lista" | sort > "$tmp/local"
"${SSH[@]}" "cd '$RUTA' 2>/dev/null && xargs -d '\\n' sha256sum 2>/dev/null; true" < "$tmp/lista" | sort > "$tmp/remoto"
comm -23 "$tmp/local" "$tmp/remoto" | cut -c67- > "$tmp/cambios"

n=$(wc -l < "$tmp/cambios")
if [[ $n -eq 0 ]]; then
  echo "El servidor ya está al día ($(wc -l < "$tmp/lista") ficheros)."
  exit 0
fi
tamano=$(xargs -d '\n' du -cb < "$tmp/cambios" | tail -1 | cut -f1)
echo "Cambiados: $n ficheros, $((tamano / 1024 / 1024)) MB"
[[ $MODO == simular ]] && { sed 's/^/  /' "$tmp/cambios"; exit 0; }

tar cf - -T "$tmp/cambios" | "${SSH[@]}" -C \
  "tar xf - -C '$RUTA' --no-same-owner && chown -R '$USUARIO_APP:$USUARIO_APP' '$RUTA'"
echo "Enviado a $DESTINO:$RUTA"

# el código y config.json se leen al arrancar; los datos se recargan solos
if grep -qE '^(jenui/|scripts/server\.py|config\.json|requirements\.txt)' "$tmp/cambios"; then
  if "${SSH[@]}" "systemctl is-active --quiet jenui"; then
    "${SSH[@]}" "systemctl restart jenui" && echo "Servicio jenui reiniciado (cambió código o configuración)."
  else
    echo "Cambió código o configuración; el servicio jenui no está en marcha (arráncalo con: systemctl start jenui)."
  fi
fi
