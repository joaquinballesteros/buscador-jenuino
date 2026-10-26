#!/usr/bin/env python3
"""Análisis temporal de topics: emergentes, consolidados y recurrentes.

Lee el corpus y el grafo ya construido del buscador (no llama al LLM) y
escribe en data/analysis/ los CSV, un JSON completo y un informe HTML con las
gráficas. Tarda segundos. Ejecutar desde la raíz del proyecto:

    python scripts/topic_evolution.py
    python scripts/topic_evolution.py --resolucion 1.5       # topics más finos
    python scripts/topic_evolution.py --desde 1997 --hasta 2026
    python scripts/topic_evolution.py --fuente keywords      # sin grafo: palabras clave
    python scripts/topic_evolution.py --rag-dir rag_storage_meta   # otro grafo

Los parámetros están en config.json -> analysis. La lógica vive en
jenui.analysis.TopicAnalysis.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from collections import Counter

from jenui.analysis import AnalysisOptions, ReportWriter, TopicAnalysis
from jenui.analysis.concept_source import SOURCES
from jenui.config import Paths, Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolución temporal de los topics de JENUI.")
    parser.add_argument("--fuente", choices=SOURCES, default=None,
                        help="origen de los conceptos (por defecto, config.json -> analysis.fuente)")
    parser.add_argument("--rag-dir", default=None,
                        help="almacén de LightRAG a leer (por defecto, analysis.grafo_dir)")
    parser.add_argument("--desde", type=int, default=None, help="primer año")
    parser.add_argument("--hasta", type=int, default=None, help="último año")
    parser.add_argument("--resolucion", type=float, default=None,
                        help="resolución de Louvain: más alta, topics más pequeños")
    parser.add_argument("--min-articulos", type=int, default=None,
                        help="artículos mínimos para que un concepto cuente")
    parser.add_argument("--salida", default=None,
                        help="carpeta de resultados (por defecto, data/analysis)")
    args = parser.parse_args()

    base = Settings.load()
    rag_dir = args.rag_dir or base.section("analysis").get("grafo_dir")
    settings = Settings.load(Paths.default().with_rag_dir(rag_dir))

    result = TopicAnalysis(settings, AnalysisOptions(
        source=args.fuente, year_from=args.desde, year_to=args.hasta,
        resolution=args.resolucion, min_df=args.min_articulos,
    )).run()

    out_dir = Path(args.salida) if args.salida else settings.paths.analysis_dir
    written = ReportWriter(out_dir).write(result)
    summarize(result)
    print("\nFicheros:")
    for path in written:
        print(f"  {path}")


def summarize(result: dict) -> None:
    topics = result["topics"]
    classes = Counter(t["clase"] for t in topics)
    print("\nTopics por clase:")
    for name in result["meta"]["clases"]:
        if classes[name]:
            print(f"  {name:22} {classes[name]}")

    for name in ("emergente consolidado", "emergente reciente", "recurrente"):
        chosen = [t for t in topics if t["clase"] == name][:8]
        if not chosen:
            continue
        print(f"\n--- {name} ---")
        for t in chosen:
            since = f"desde {t['anio_inicio']}" if t["anio_inicio"] else ""
            print(f"  {t['id']}  {t['n_articulos']:4} art.  {since:11} {t['label'][:70]}")

    hubs = result["meta"]["hubs"]
    if hubs:
        print("\nExcluidos por demasiado frecuentes (revisa max_fraccion_concepto):")
        print("  " + ", ".join(f"{h['concepto']} ({h['articulos']})" for h in hubs[:12]))


if __name__ == "__main__":
    main()
