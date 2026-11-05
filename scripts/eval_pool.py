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

#: Configuraciones que se comparan: cambios sobre config.json -> search. Cada
#: una fija todos los parámetros que la distinguen, para que su nombre siga
#: significando lo mismo aunque cambien los valores por defecto de config.json.
ANTERIOR = {  # hasta el 2026-11-05: 3 semillas, límite 12, sin normalizar, 15 resultados
    "normalizacion": "ninguna", "peso_texto": 0.85, "peso_grafo": 0.3,
    "n_semillas": 3, "margen_semilla": None, "max_articulos_por_entidad": 12,
    "conceptos_consulta": 0, "max_conceptos_semilla": 20,
    "corte": "umbral", "umbral_resultado": None, "top_k": 15,
}
_GRAFO = {  # expansión por el grafo por umbrales de similitud, sin topes
    "n_semillas": None, "margen_semilla": 0.05, "max_articulos_por_entidad": 30,
    "conceptos_consulta": None, "umbral_concepto_consulta": 0.3,
    "margen_concepto_consulta": 0.06, "max_conceptos_semilla": None,
}
UMBRAL_MINMAX = {  # 2026-11-05: min-max sobre 200 y corte en 0,4
    **_GRAFO, "normalizacion": "minmax", "candidatos_normalizacion": 200,
    "peso_texto": 0.6, "peso_grafo": 0.4,
    "corte": "umbral", "umbral_resultado": 0.4, "top_k": 100,
}
NUEVA = {  # similitud real + bonus del grafo; corte por sorpresa (teoría de valores extremos)
    **_GRAFO, "normalizacion": "bonus", "bonus_grafo": 0.05, "referencia_grafo": 1.0,
    "corte": "sorpresa", "umbral_sorpresa": 3.0, "profundidad_sorpresa": 200,
    "top_k": 100,
}
#: Profundidad hasta la que se juzga el ranking nuevo: cualquier corte (k fijo,
#: umbral global, sorpresa) hasta aquí se evalúa sin artículos sin juzgar.
PROFUNDIDAD = 20

VARIANTS = {
    "texto": {**NUEVA, "bonus_grafo": 0.0, "corte": None, "top_k": 10},
    "anterior": ANTERIOR,
    "umbral_minmax": UMBRAL_MINMAX,
    "nueva": NUEVA,
    "nueva_ranking": {**NUEVA, "corte": None, "top_k": PROFUNDIDAD},
}


def pooled(results: list[dict], overrides: dict, top: int, max_list: int) -> list[dict]:
    """Lo que una configuración aporta al pool.

    Con corte (umbral o sorpresa), su lista entera hasta ``max_list``: el ruido
    está en la cola y hay que juzgarlo. Sin corte, su lista tal cual (su
    ``top_k``), o los ``top`` primeros si no lo fija.
    """
    cuts = overrides.get("corte") == "sorpresa" or overrides.get("umbral_resultado") is not None
    if cuts:
        return results[:max_list]
    return results if "top_k" in overrides else results[:top]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pooling de candidatos para juzgar.")
    parser.add_argument("--variantes", nargs="+", choices=list(VARIANTS),
                        default=list(VARIANTS), help="configuraciones a combinar")
    parser.add_argument("--top", type=int, default=10,
                        help="resultados que aporta al pool una configuración sin umbral")
    parser.add_argument("--max-lista", type=int, default=40,
                        help="tope de la lista que aporta una configuración con umbral")
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
            results = searcher.search(q["consulta"])["results"]
            chosen = pooled(results, VARIANTS[name], args.top, args.max_lista)
            found[q["id"]].update(r["id"] for r in chosen)
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
