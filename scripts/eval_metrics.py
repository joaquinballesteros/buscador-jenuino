#!/usr/bin/env python3
"""Métricas del banco de evaluación de la búsqueda.

Con los juicios de evaluacion/juicios/*.csv (juicio de referencia = mediana de
los evaluadores) calcula el acuerdo entre evaluadores y, para cada
configuración del buscador, nDCG@10, recall@10 y judged@10. Ejecutar desde la
raíz del proyecto:

    python scripts/eval_metrics.py                         # las configuraciones de eval_pool.py
    python scripts/eval_metrics.py --barrido peso_grafo=0,0.15,0.3,0.5 \\
                                   --fijo normalizacion=minmax
    python scripts/eval_metrics.py --min-evaluadores 2

La precisión de la lista (qué fracción de lo devuelto es relevante) mide el
ruido cuando la lista se corta por umbral. judged@10 es la fracción del top-10 con juicio: lo no juzgado cuenta como no
relevante, así que una configuración que trae muchos artículos nuevos sale
penalizada. Si judged@10 baja de ~0,9, amplía el pool (eval_pool.py) y juzga
lo nuevo antes de fiarte de la comparación.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import itertools
import json
import statistics

from eval_pool import VARIANTS

from jenui.config import Settings
from jenui.evaluation import JudgmentStore
from jenui.evaluation.metrics import (judged_at, krippendorff_alpha_ordinal,
                                      ndcg_at, precision, recall_at)
from jenui.search.searcher import Searcher


def parse_value(text: str):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def configurations(args) -> dict[str, dict]:
    fixed = {k: parse_value(v) for k, v in (f.split("=", 1) for f in args.fijo)}
    if not args.barrido:
        return {name: {**fixed, **values} for name, values in VARIANTS.items()}
    axes = [(k, [parse_value(v) for v in vs.split(",")])
            for k, vs in (b.split("=", 1) for b in args.barrido)]
    configs = {}
    for combo in itertools.product(*(values for _, values in axes)):
        values = dict(zip((k for k, _ in axes), combo))
        configs[" ".join(f"{k}={v}" for k, v in values.items())] = {**fixed, **values}
    return configs


def agreement(store: JudgmentStore) -> dict:
    votes = store.all_judgments()
    units = [list(v.values()) for v in votes.values()]
    per_query: dict[str, list[list[int]]] = {}
    for (query_id, _), v in votes.items():
        per_query.setdefault(query_id, []).append(list(v.values()))
    return {
        "evaluadores": store.evaluators(),
        "pares_con_varios_juicios": sum(len(u) >= 2 for u in units),
        "alfa_global": krippendorff_alpha_ordinal(units),
        "alfa_por_consulta": {q: krippendorff_alpha_ordinal(u) for q, u in sorted(per_query.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Métricas del banco de evaluación.")
    parser.add_argument("--barrido", nargs="*", default=[],
                        help="clave=v1,v2,... de config.json -> search (producto cartesiano)")
    parser.add_argument("--fijo", nargs="*", default=[],
                        help="clave=valor fijo para todas las configuraciones")
    parser.add_argument("--min-evaluadores", type=int, default=1,
                        help="solo cuentan los pares juzgados por al menos N personas")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    base = Settings.load()
    store = JudgmentStore(base.paths.evaluation_dir)
    qrels: dict[str, dict[str, float]] = {}
    for (query_id, article_id), gain in store.consensus(args.min_evaluadores).items():
        qrels.setdefault(query_id, {})[article_id] = gain
    queries = [q for q in store.queries() if q["id"] in qrels]
    if not queries:
        raise SystemExit("Aún no hay juicios en evaluacion/juicios/.")

    agree = agreement(store)
    alpha = agree["alfa_global"]
    print(f"Evaluadores: {', '.join(agree['evaluadores'])}  |  consultas con juicios: "
          f"{len(queries)}  |  pares con >=2 juicios: {agree['pares_con_varios_juicios']}")
    print(f"Acuerdo (alfa de Krippendorff ordinal): "
          f"{'—' if alpha is None else f'{alpha:.3f}'}  (>=0,8 fiable; >=0,667 provisional)")
    weak = [q for q, a in agree["alfa_por_consulta"].items() if a is not None and a < 0.667]
    if weak:
        print(f"Consultas con poco acuerdo (revisa su criterio): {', '.join(weak)}")

    k = args.k
    results = {}
    print(f"\n{'configuración':24} nDCG@{k}  recall@{k}  judged@{k} | lista: longitud  precisión  juzgada")
    for name, overrides in configurations(args).items():
        searcher = Searcher(base.with_overrides("search", overrides))
        rows = {}
        for q in queries:
            full = [r["id"] for r in searcher.search(q["consulta"])["results"]]
            judged = qrels[q["id"]]
            rows[q["id"]] = {"ndcg": ndcg_at(full, judged, k),
                             "recall": recall_at(full, judged, k),
                             "judged": judged_at(full, judged, k),
                             "longitud": len(full),
                             "precision_lista": precision(full, judged),
                             "juzgada_lista": judged_at(full, judged, len(full) or 1)}
        mean = {m: statistics.mean(r[m] for r in rows.values())
                for m in ("ndcg", "recall", "judged", "longitud", "precision_lista", "juzgada_lista")}
        results[name] = {"cambios": overrides, "media": mean, "por_consulta": rows}
        print(f"{name:24} {mean['ndcg']:7.3f}  {mean['recall']:9.3f}  {mean['judged']:9.2f} | "
              f"{mean['longitud']:13.1f}  {mean['precision_lista']:9.3f}  {mean['juzgada_lista']:7.2f}")

    out = store.queries_file.parent / "resultados.json"
    out.write_text(json.dumps({"k": k, "acuerdo": agree, "configuraciones": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDetalle por consulta -> {out}")


if __name__ == "__main__":
    main()
