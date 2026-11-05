#!/usr/bin/env python3
"""Estudio de truncado: dónde cortar la lista de resultados.

Compara, sobre el MISMO ranking (configuración "nueva" de eval_pool.py), tres
formas de decidir cuántos resultados devolver, siguiendo la metodología de la
literatura de truncado de listas (Arampatzis et al., SIGIR 2009; Bahri et al.,
SIGIR 2023):

* **k fijo** — siempre los k primeros;
* **umbral global** — los de puntuación ≥ τ (en unidades de similitud);
* **sorpresa** — teoría de valores extremos: sorpresa −log p ≥ τ;
* **sorpresa + suelo** — además, puntuación ≥ un suelo absoluto: la sorpresa
  calibra entre consultas pero es relativa a cada una, y el suelo conserva la
  información absoluta de la similitud (en la línea de los predictores de
  calidad de consulta basados en la puntuación).

Métrica: F1 por consulta (relevante = mediana de los evaluadores ≥ 1). El
parámetro de cada método se elige con **validación cruzada dejando una
consulta fuera**, para no sobreajustar con un banco pequeño. Además, se aplica
a las consultas ajenas a JENUI (evaluacion/consultas_ajenas.csv), cuya
respuesta correcta es no devolver nada. Ejecutar desde la raíz del proyecto:

    python scripts/eval_truncado.py
    python scripts/eval_truncado.py --min-evaluadores 2
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import csv
import json
import statistics

import numpy as np
from eval_pool import NUEVA

from jenui.config import Settings
from jenui.evaluation import JudgmentStore
from jenui.search.searcher import Searcher

PROFUNDIDAD_LISTA = 40          # hasta dónde se miran los cortes (lo que se juzgó)
METODOS = {
    "k fijo": ("k", list(range(0, 21))),
    "umbral global": ("τ (similitud)", [round(float(x), 3) for x in np.arange(0.40, 0.80, 0.005)]),
    "sorpresa": ("τ (−log p)", [round(float(x), 2) for x in np.arange(0.0, 12.01, 0.25)]),
    "sorpresa + suelo": ("(τ, suelo)", [(round(float(t), 2), round(float(f), 3))
                                        for t in np.arange(0.0, 8.01, 0.5)
                                        for f in np.arange(0.40, 0.651, 0.025)]),
}


def cut(method: str, param, rows: list[dict]) -> list[str]:
    if method == "k fijo":
        return [r["id"] for r in rows[:param]]
    if method == "umbral global":
        return [r["id"] for r in rows if r["score"] >= param]
    if method == "sorpresa":
        return [r["id"] for r in rows if (r["sorpresa"] or 0.0) >= param]
    tau, floor = param
    return [r["id"] for r in rows if (r["sorpresa"] or 0.0) >= tau and r["score"] >= floor]


def f1(selected: list[str], judged: dict[str, float]) -> tuple[float, float, float]:
    """(F1, precisión, recall). Sin relevantes juzgados, acertar es no devolver nada."""
    relevant = {a for a, g in judged.items() if g >= 1}
    if not relevant:
        ok = float(not selected)
        return ok, ok, ok
    hits = len(relevant & set(selected))
    if not hits:
        return 0.0, 0.0, 0.0
    p, r = hits / len(selected), hits / len(relevant)
    return 2 * p * r / (p + r), p, r


def main() -> None:
    parser = argparse.ArgumentParser(description="Estudio de truncado de la lista.")
    parser.add_argument("--min-evaluadores", type=int, default=1)
    args = parser.parse_args()

    base = Settings.load()
    store = JudgmentStore(base.paths.evaluation_dir)
    qrels: dict[str, dict[str, float]] = {}
    for (qid, aid), gain in store.consensus(args.min_evaluadores).items():
        qrels.setdefault(qid, {})[aid] = gain
    queries = [q for q in store.queries() if q["id"] in qrels]
    if not queries:
        raise SystemExit("Aún no hay juicios en evaluacion/juicios/.")
    ajenas_file = store.queries_file.parent / "consultas_ajenas.csv"
    ajenas = list(csv.DictReader(open(ajenas_file, encoding="utf-8"))) if ajenas_file.exists() else []

    # el ranking nuevo con la sorpresa de cada resultado (sin cortar)
    searcher = Searcher(base.with_overrides("search", {**NUEVA, "umbral_sorpresa": -1.0,
                                                        "top_k": PROFUNDIDAD_LISTA}))
    lists = {q["id"]: searcher.search(q["consulta"])["results"] for q in queries}
    ajenas_lists = {q["id"]: searcher.search(q["consulta"])["results"] for q in ajenas}

    print(f"Consultas con juicios: {len(queries)}  |  consultas ajenas: {len(ajenas)}\n")
    print(f"{'método':17} {'parámetro':>22} | {'F1 (VC)':>8} {'precisión':>9} {'recall':>7} {'longitud':>8} | ajenas vacías")
    report = {}
    for method, (label, grid) in METODOS.items():
        # F1 de cada consulta para cada valor del parámetro
        table = np.array([[f1(cut(method, p, lists[q["id"]]), qrels[q["id"]])[0] for p in grid]
                          for q in queries])
        # validación cruzada dejando una consulta fuera
        held_out, chosen = [], []
        for i, q in enumerate(queries):
            others = np.delete(table, i, axis=0).mean(axis=0)
            best = int(np.argmax(others))
            chosen.append(grid[best])
            sel = cut(method, grid[best], lists[q["id"]])
            held_out.append((*f1(sel, qrels[q["id"]]), len(sel)))
        best_all = grid[int(np.argmax(table.mean(axis=0)))]
        empty = sum(not cut(method, best_all, ajenas_lists[q["id"]]) for q in ajenas)
        f, p, r, n = (statistics.mean(x[i] for x in held_out) for i in range(4))
        report[method] = {"parametro": best_all, "f1_vc": f, "precision": p, "recall": r,
                          "longitud": n, "ajenas_vacias": empty, "ajenas": len(ajenas),
                          "parametros_vc": chosen}
        print(f"{method:17} {label + ' ' + str(best_all):>22} | {f:8.3f} {p:9.3f} {r:7.3f} {n:8.1f} | "
              f"{empty}/{len(ajenas)}")

    # aviso de similitud baja (no oculta resultados; solo avisa)
    plain = Searcher(base)
    warned_bench = sum(bool(plain.search(q["consulta"])["aviso"]) for q in queries)
    warned_out = sum(bool(plain.search(q["consulta"])["aviso"]) for q in ajenas)
    threshold = base.search.get("umbral_aviso_similitud")
    print(f"\nAviso de similitud baja (umbral {threshold}): consultas del banco con aviso "
          f"{warned_bench}/{len(queries)} (deberían ser 0) · ajenas con aviso {warned_out}/{len(ajenas)}")
    report["aviso_similitud_baja"] = {"umbral": threshold, "banco": warned_bench,
                                      "ajenas": warned_out}

    out = store.queries_file.parent / "resultados_truncado.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nF1 (VC): validación cruzada dejando una consulta fuera; el parámetro mostrado es el "
          f"óptimo con todas las consultas.\nDetalle -> {out}")


if __name__ == "__main__":
    main()
