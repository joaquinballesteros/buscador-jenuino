#!/usr/bin/env python3
"""Índice vectorial de texto completo (solo embeddings, sin LLM).

Incremental: embebe únicamente los artículos que aún no están indexados.

    python build_fulltext.py             # solo lo nuevo
    python build_fulltext.py --rebuild   # reconstruye el índice entero

La lógica vive en jenui.indexing.VectorIndexBuilder.
"""
import argparse

from jenui.config import Settings
from jenui.indexing import VectorIndexBuilder
from jenui.ingestion import CorpusRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Construcción incremental del índice vectorial de texto completo.")
    parser.add_argument("--rebuild", action="store_true",
                        help="reconstruye todo el índice (por defecto solo lo nuevo)")
    args = parser.parse_args()

    settings = Settings.load()
    articles = CorpusRepository(settings.paths.corpus_file).load_all()
    if not articles:
        raise SystemExit("El corpus está vacío. Ejecuta ingest.py primero.")

    report = VectorIndexBuilder(settings).build(articles, rebuild=args.rebuild)
    if not report.new_articles:
        print("Nada nuevo que embeber.")
        return
    print(f"\nHecho en {report.seconds / 60:.1f} min. "
          f"{report.new_chunks} fragmentos nuevos, "
          f"{report.total_chunks} en total.")


if __name__ == "__main__":
    main()
