#!/usr/bin/env python3
"""Fusión semántica de entidades equivalentes del grafo.

LightRAG fusiona entidades solo por nombre exacto, así que el mismo concepto
acaba partido y deja de conectar artículos:

    'Investigación-acción'  'Formación en Investigación-Acción'
    'ABP'                   'Aprendizaje basado en proyectos'

Genera data/entity_aliases.json, que el buscador aplica al cargar el grafo.
Local y sin LLM: solo cuesta tiempo de embeddings.

    python merge_aliases.py                 # umbral de config.json
    python merge_aliases.py --dry-run       # muestra qué fusionaría, sin escribir
    python merge_aliases.py --umbral 0.95   # más estricto

La lógica vive en jenui.graph.SemanticAliasBuilder.
"""
import argparse

from jenui.config import Settings
from jenui.graph import SemanticAliasBuilder


def main() -> None:
    settings = Settings.load()
    builder = SemanticAliasBuilder(settings)

    parser = argparse.ArgumentParser(
        description="Fusión semántica de entidades equivalentes del grafo."
    )
    parser.add_argument("--umbral", type=float, default=builder.default_threshold,
                        help="similitud coseno mínima para fusionar")
    parser.add_argument("--dry-run", action="store_true",
                        help="solo mostrar, no guardar")
    parser.add_argument("--batch", type=int, default=32)
    args = parser.parse_args()

    report = builder.build(threshold=args.umbral, batch_size=args.batch)

    print(f"\nGrupos finales: {report.groups_final}  |  "
          f"fusiones semánticas: {report.n_merges}")
    print(f"Tiempo: {report.seconds / 60:.1f} min\n")
    print("--- fusiones más seguras ---")
    for source, target, score in report.top_merges():
        print(f"  {score:.3f}  {source[:45]:45} -> {target[:45]}")

    if args.dry_run:
        print("\n(--dry-run: no se ha escrito nada)")
        return
    builder.save(report.aliases)
    print(f"\nGuardados {len(report.aliases)} alias -> {settings.paths.aliases_file}")
    print("El buscador los aplicará al recargar el grafo.")


if __name__ == "__main__":
    main()
