#!/usr/bin/env python3
"""Ingesta de PDFs y fichas -> data/corpus.jsonl

Incremental: solo procesa los artículos que aún no están en el corpus.
Ejecutar desde la raíz del proyecto:

    python scripts/ingest.py              # solo lo nuevo
    python scripts/ingest.py --rebuild    # reprocesa todo desde cero
    python scripts/ingest.py --reparar    # repara resúmenes y textos ilegibles del corpus

La lógica vive en jenui.ingestion.CorpusBuilder.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from jenui.config import Settings
from jenui.ingestion import CorpusBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta incremental de PDFs y fichas hacia el corpus.")
    parser.add_argument("--rebuild", action="store_true",
                        help="reprocesa TODOS los PDFs (por defecto solo los nuevos)")
    parser.add_argument("--limit", type=int, default=None,
                        help="procesa como mucho N artículos nuevos")
    parser.add_argument("--reparar", action="store_true",
                        help="solo repara los textos ilegibles del corpus ya construido "
                             "(fuentes mal codificadas), sin releer los PDFs")
    args = parser.parse_args()

    builder = CorpusBuilder(Settings.load())
    if args.reparar:
        repaired = builder.repair_existing()
        print(f"Artículos reparados: {repaired}")
        return
    if args.rebuild:
        print("Modo --rebuild: se reconstruye el corpus completo.")
    report = builder.build(rebuild=args.rebuild, limit=args.limit)

    print(f"\nPDFs: {report.total_pdfs}  |  ya en corpus: {report.already_indexed}  "
          f"|  procesados ahora: {report.processed}")
    if report.repaired:
        print(f"Textos ilegibles reparados: {report.repaired}")
    if report.failed:
        print(f"Fallaron {len(report.failed)}: {', '.join(report.failed)}")
    if not report.processed:
        print("Nada nuevo que procesar.")


if __name__ == "__main__":
    main()
