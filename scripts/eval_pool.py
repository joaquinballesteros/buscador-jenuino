#!/usr/bin/env python3
"""Candidatos a juzgar para el banco de evaluación de la búsqueda (pooling).

Para cada consulta de evaluacion/consultas.csv junta los mejores resultados de
varias configuraciones del buscador y los guarda, en orden aleatorio, en
evaluacion/candidatos.json. Luego se juzgan en la página /evaluar. Ejecutar
desde la raíz del proyecto:

    python scripts/eval_pool.py                       # todas las configuraciones
    python scripts/eval_pool.py --variantes texto     # solo texto (sin grafo)
    python scripts/eval_pool.py --top 15

Es acumulativo: los candidatos que ya había se conservan en su sitio y los
nuevos se añaden al final, así que se puede empezar a juzgar con una
configuración y ampliar después sin perder ni descolocar lo ya juzgado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import random

from jenui.config import Settings
from jenui.evaluation import JudgmentStore
from jenui.search.searcher import Searcher

#: Configuraciones que se comparan: cambios sobre config.json -> search.
VARIANTS = {
    "texto": {"peso_grafo": 0.0},
    "grafo": {"normalizacion": "ninguna"},
    "minmax": {"normalizacion": "minmax"},
    "rrf": {"normalizacion": "rrf"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Pooling de candidatos para juzgar.")
    parser.add_argument("--variantes", nargs="+", choices=list(VARIANTS),
                        default=list(VARIANTS), help="configuraciones a combinar")
    parser.add_argument("--top", type=int, default=10,
                        help="resultados de cada configuración que entran al pool")
    parser.add_argument("--semilla", type=int, default=42)
    args = parser.parse_args()

    base = Settings.load()
    store = JudgmentStore(base.paths.evaluation_dir)
    queries = store.queries()
    if not queries:
        raise SystemExit(f"No hay consultas en {store.queries_file}")

    found: dict[str, set[str]] = {q["id"]: set() for q in queries}
    for name in args.variantes:
        searcher = Searcher(base.with_overrides("search", VARIANTS[name]))
        for q in queries:
            results = searcher.search(q["consulta"], top_k=args.top)["results"]
            found[q["id"]].update(r["id"] for r in results)
        print(f"  {name}: hecho")

    pool = store.candidates()
    added = 0
    for q in queries:
        current = pool.get(q["id"], [])
        new = sorted(found[q["id"]] - set(current))
        random.Random(f"{args.semilla}-{q['id']}-{len(current)}").shuffle(new)
        pool[q["id"]] = current + new
        added += len(new)
    store.save_candidates(pool)

    total = sum(len(v) for v in pool.values())
    print(f"\nCandidatos nuevos: {added}  |  total: {total} "
          f"({total / len(queries):.1f} por consulta)  ->  {store.candidates_file}")


if __name__ == "__main__":
    main()
