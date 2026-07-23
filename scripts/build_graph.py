#!/usr/bin/env python3
"""Construcción del grafo de conocimiento (LightRAG).

Incremental y reanudable: LightRAG salta los documentos ya procesados, así que
puedes cortar con Ctrl-C y relanzarlo, o volver a lanzarlo tras añadir artículos.
Ejecutar desde la raíz del proyecto:

    python scripts/build_graph.py                # ámbito de config.json
    python scripts/build_graph.py --scope full   # texto completo (más lento, más rico)
    python scripts/build_graph.py --limit 2      # prueba con 2 artículos

La lógica vive en jenui.indexing.GraphBuilder.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio

from jenui.config import Settings
from jenui.indexing import GraphBuilder
from jenui.ingestion import CorpusRepository


async def run(limit: int | None, scope: str | None) -> None:
    settings = Settings.load()
    articles = CorpusRepository(settings.paths.corpus_file).load_all()
    if not articles:
        raise SystemExit("El corpus está vacío. Ejecuta scripts/ingest.py primero.")
    if limit:
        articles = articles[:limit]

    report = await GraphBuilder(settings).build(articles, scope=scope)
    print(f"\nHecho en {report.seconds / 60:.1f} min. "
          f"Grafo en {settings.paths.rag_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Construcción incremental del grafo de conocimiento.")
    parser.add_argument("--limit", type=int, default=None,
                        help="indexar solo N artículos")
    parser.add_argument("--scope", choices=["meta", "full"], default=None,
                        help="meta=título+resumen+keywords; full=texto completo. "
                             "Por defecto, config.json -> graph.scope")
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.scope))


if __name__ == "__main__":
    main()
