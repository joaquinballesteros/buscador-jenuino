#!/usr/bin/env bash
# Análisis temporal de topics, usando el entorno virtual del proyecto.
# Por defecto analiza el grafo ya construido del buscador (rag_storage): no
# llama al LLM y tarda segundos.
#
#   ./scripts/topic_pipeline.sh                # análisis del grafo existente
#   ./scripts/topic_pipeline.sh --referencias  # antes, regenera fuentes/referencias_jenui.csv
#   ./scripts/topic_pipeline.sh --grafo-meta   # opcional: grafo aparte solo con resúmenes
#                                              # (rag_storage_meta; llama al LLM, reanudable)
#
# Lo que sigue a "--" se pasa a topic_evolution.py, p. ej.:
#   ./scripts/topic_pipeline.sh -- --resolucion 1.5
set -euo pipefail
cd "$(dirname "$0")/.."

META_DIR="rag_storage_meta"
REFERENCIAS=0
GRAFO_META=0
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --referencias) REFERENCIAS=1 ;;
    --grafo-meta) GRAFO_META=1 ;;
    --) shift; EXTRA=("$@"); break ;;
    *) echo "Opción desconocida: $1"; exit 1 ;;
  esac
  shift
done

if [[ ! -x .venv/bin/python ]]; then
  echo "No existe .venv. Créalo con:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
PY=.venv/bin/python

step() { echo; echo "=== $* ==="; }

if [[ $REFERENCIAS -eq 1 ]]; then
  step "Referencias bibliográficas (para validar con citas)"
  $PY scripts/extract_references.py
fi

if [[ $GRAFO_META -eq 1 ]]; then
  step "Grafo aparte en $META_DIR (reanudable; progreso: python scripts/status.py --watch --rag-dir $META_DIR)"
  $PY scripts/build_graph.py --scope meta --sin-metadatos --rag-dir "$META_DIR"
  step "Fusión semántica de entidades de $META_DIR"
  $PY scripts/merge_aliases.py --rag-dir "$META_DIR"
  EXTRA=(--rag-dir "$META_DIR" ${EXTRA[@]+"${EXTRA[@]}"})
fi

step "Análisis temporal"
$PY scripts/topic_evolution.py ${EXTRA[@]+"${EXTRA[@]}"}

echo
echo "Abre data/analysis/informe_topics.html en el navegador."
