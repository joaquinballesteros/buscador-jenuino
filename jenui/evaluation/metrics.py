"""Métricas de evaluación: calidad del ranking y acuerdo entre evaluadores."""
from __future__ import annotations

import math
from collections import Counter


def dcg(gains: list[float]) -> float:
    """DCG con ganancia exponencial (2^g - 1): un 2 vale tres veces un 1."""
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ranking: list[str], judged: dict[str, float], k: int = 10) -> float:
    """nDCG@k. Lo no juzgado cuenta como 0; el ideal sale de todo lo juzgado."""
    ideal = dcg(sorted(judged.values(), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([judged.get(a, 0.0) for a in ranking[:k]]) / ideal


def recall_at(ranking: list[str], judged: dict[str, float], k: int = 10,
              threshold: float = 1.0) -> float:
    """Fracción de los relevantes juzgados (mediana >= ``threshold``) en el top-k."""
    relevant = {a for a, g in judged.items() if g >= threshold}
    if not relevant:
        return 0.0
    return len(relevant & set(ranking[:k])) / len(relevant)


def precision(ranking: list[str], judged: dict[str, float],
              threshold: float = 1.0) -> float:
    """Fracción de la lista que es relevante (mediana >= ``threshold``).

    Es la medida del ruido cuando la lista se corta por umbral y no por número.
    Lo no juzgado cuenta como no relevante: mira también judged_at sobre la lista.
    """
    if not ranking:
        return 0.0
    return sum(judged.get(a, 0.0) >= threshold for a in ranking) / len(ranking)


def judged_at(ranking: list[str], judged: dict[str, float], k: int = 10) -> float:
    """Fracción del top-k que tiene juicio. Si es baja, la métrica es poco fiable."""
    top = ranking[:k]
    return sum(a in judged for a in top) / len(top) if top else 0.0


def krippendorff_alpha_ordinal(units: list[list[int]]) -> float | None:
    """Alfa de Krippendorff con métrica ordinal.

    ``units`` es una lista de unidades (cada par consulta-artículo) con los
    valores que le dieron los evaluadores. Las unidades con un solo juicio no
    aportan. 1 = acuerdo perfecto, 0 = el que cabría por azar. Como referencia
    habitual, >= 0,8 es fiable y >= 0,667 admite conclusiones provisionales.
    """
    coincidence: Counter = Counter()
    for values in units:
        m = len(values)
        if m < 2:
            continue
        counts = Counter(values)
        for c in counts:
            for k in counts:
                pairs = counts[c] * (counts[k] - (c == k))
                coincidence[c, k] += pairs / (m - 1)
    if not coincidence:
        return None
    categories = sorted({c for c, _ in coincidence})
    n_c = {c: sum(coincidence[c, k] for k in categories) for c in categories}
    n = sum(n_c.values())
    if n <= 1 or len(categories) < 2:
        return None

    def delta2(c: int, k: int) -> float:
        lo, hi = min(c, k), max(c, k)
        between = sum(n_c[g] for g in categories if lo <= g <= hi)
        return (between - (n_c[c] + n_c[k]) / 2) ** 2

    observed = sum(coincidence[c, k] * delta2(c, k) for c in categories for k in categories) / n
    expected = sum(n_c[c] * n_c[k] * delta2(c, k)
                   for c in categories for k in categories) / (n * (n - 1))
    return 1.0 - observed / expected if expected else None
