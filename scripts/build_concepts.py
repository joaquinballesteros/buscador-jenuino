#!/usr/bin/env python3
"""Índice de vectores de concepto (nombre + descripción) para el filtro de relevancia.

Mejora la separación entre conceptos afines y ajenos a una consulta, embebiendo
cada entidad junto con su descripción y guardando el vector medio (para centrar).
Local y sin LLM. Ejecutar tras construir el grafo, desde la raíz del proyecto:

    python scripts/build_concepts.py

La lógica vive en jenui.graph.ConceptEmbeddingBuilder.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jenui.config import Settings
from jenui.graph.concept_embedding_builder import ConceptEmbeddingBuilder


def main() -> None:
    report = ConceptEmbeddingBuilder(Settings.load()).build()
    print(f"\nHecho en {report.seconds / 60:.1f} min. "
          f"{report.concepts} conceptos -> data/concept_vectors.npz")
    print("El buscador lo usará al recargar (mejor separación por relevancia).")


if __name__ == "__main__":
    main()
