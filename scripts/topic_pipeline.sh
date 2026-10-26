#!/usr/bin/env bash
# Análisis temporal de topics de principio a fin, usando el entorno virtual
# del proyecto. Todos los pasos son incrementales o reanudables: si se corta
# (o falla la API), basta con volver a lanzarlo.
#
#   ./scripts/topic_pipeline.sh                 # ingesta + grafo + alias + análisis
#   ./scripts/topic_pipeline.sh --descargar     # además, descarga los PDFs y fichas que falten
#   ./scripts/topic_pipeline.sh --referencias   # además, regenera fuentes/referencias_jenui.csv
#   ./scripts/topic_pipeline.sh --solo-analisis # solo el último paso (segundos)
#
# Lo que sigue a "--" se pasa a topic_evolution.py, p. ej.:
#   ./scripts/topic_pipeline.sh --solo-analisis -- --resolucion 1.5
set -euo pipefail
cd "$(dirname "$0")/.."

RAG_DIR="rag_storage_meta"
DESCARGAR=0
REFERENCIAS=0
SOLO_ANALISIS=0
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --descargar) DESCARGAR=1 ;;
    --referencias) REFERENCIAS=1 ;;
    --solo-analisis) SOLO_ANALISIS=1 ;;
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

if [[ $SOLO_ANALISIS -eq 0 ]]; then
  if [[ $DESCARGAR -eq 1 ]]; then
    step "1/5 Descarga de PDFs y fichas"
    $PY scripts/download_sources.py
  fi

  step "2/5 Ingesta (solo artículos nuevos)"
  $PY scripts/ingest.py

  if [[ $REFERENCIAS -eq 1 ]]; then
    step "3/5 Referencias bibliográficas"
    $PY scripts/extract_references.py
  fi

  step "4/5 Grafo del análisis en $RAG_DIR (reanudable; progreso: python scripts/status.py --watch --rag-dir $RAG_DIR)"
  $PY scripts/build_graph.py --scope meta --sin-metadatos --rag-dir "$RAG_DIR"

  step "4b/5 Fusión semántica de entidades del grafo del análisis"
  $PY scripts/merge_aliases.py --rag-dir "$RAG_DIR"
fi

step "5/5 Análisis temporal"
$PY scripts/topic_evolution.py --rag-dir "$RAG_DIR" ${EXTRA[@]+"${EXTRA[@]}"}

echo
echo "Abre data/analysis/informe_topics.html en el navegador."
