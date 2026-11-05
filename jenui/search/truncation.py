"""Dónde cortar la lista de resultados: puntuación de sorpresa (teoría de valores extremos).

Implementa *Surprise scoring* (Bahri, Zheng, Tay, Metzler y Tomkins, "Surprise:
Result List Truncation via Extreme Value Theory", SIGIR 2023). Por el teorema de
Pickands-Balkema-de Haan, la cola de una distribución muy general se aproxima
por una distribución de Pareto generalizada (GPD). Se ajusta una GPD a la cola
de las puntuaciones **no relevantes** de la consulta y cada resultado recibe una
sorpresa ``S = -log p``, donde ``p`` es la probabilidad de que un no relevante
saque una puntuación así. Es una escala calibrada entre consultas sin necesidad
de entrenamiento: el umbral sobre S se elige con juicios de relevancia (el
artículo lo optimiza para F1; sin juicios, S = 3 equivale a p = 0,05).

El ajuste usa solo numpy: máxima verosimilitud con el perfil de Grimshaw (1993)
y forma xi >= 0 (cola infinita, como exige el método), y el procedimiento voraz
del artículo para separar la cola relevante y elegir el umbral de excesos
(estadístico de Cramér-von Mises).
"""
from __future__ import annotations

import numpy as np

_THETAS = np.logspace(-3, 4, 400)


def gpd_fit(excess: np.ndarray) -> tuple[float, float]:
    """MLE de la GPD (forma xi >= 0, escala sigma) sobre excesos >= 0."""
    x = np.asarray(excess, float)
    n, mean = len(x), float(x.mean()) if len(x) else 0.0
    if n < 3 or mean <= 0:
        return 0.0, max(mean, 1e-9)
    theta = _THETAS / max(float(x.max()), 1e-12)
    xi = np.log1p(np.outer(theta, x)).mean(axis=1)
    loglik = -n * np.log(xi / theta) - n - n * xi
    exponential = -n * np.log(mean) - n                 # límite xi -> 0
    k = int(np.argmax(loglik))
    if loglik[k] <= exponential:
        return 0.0, mean
    return float(xi[k]), float(xi[k] / theta[k])


def _gpd_cdf(x: np.ndarray, xi: float, sigma: float) -> np.ndarray:
    x = np.maximum(np.asarray(x, float), 0.0)
    if xi < 1e-9:
        return 1.0 - np.exp(-x / sigma)
    return 1.0 - (1.0 + xi * x / sigma) ** (-1.0 / xi)


def _cramer_von_mises(excess: np.ndarray) -> float:
    e = np.sort(excess)
    m = len(e)
    xi, sigma = gpd_fit(e)
    expected = (2 * np.arange(1, m + 1) - 1) / (2 * m)
    return float(((_gpd_cdf(e, xi, sigma) - expected) ** 2).sum() + 1.0 / (12 * m))


def surprise_scores(scores_desc, min_fit: int = 20) -> tuple[np.ndarray, dict]:
    """Sorpresa ``-log p`` de cada puntuación (lista ordenada de mayor a menor).

    1. Quita las puntuaciones más altas mientras mejore el ajuste GPD (son la
       cola relevante, que no debe entrar en el modelo de los no relevantes).
    2. Sube el umbral de excesos ``u`` desde abajo mientras mejore el ajuste.
    3. Ajusta la GPD a los excesos sobre ``u`` y puntúa toda la lista.
    """
    s = np.asarray(scores_desc, float)[::-1]           # ascendente
    n = len(s)
    if n < min_fit + 2:
        return np.zeros(n), {"u": None, "xi": None, "sigma": None}
    lo, hi = 0, n
    best = _cramer_von_mises(s[lo:hi] - s[lo])
    while hi - lo > min_fit:
        w = _cramer_von_mises(s[lo:hi - 1] - s[lo])
        if w >= best:
            break
        best, hi = w, hi - 1
    while hi - lo > min_fit:
        w = _cramer_von_mises(s[lo + 1:hi] - s[lo + 1])
        if w >= best:
            break
        best, lo = w, lo + 1
    u = float(s[lo])
    xi, sigma = gpd_fit(s[lo:hi] - u)
    x = np.maximum(s - u, 0.0)
    sur = x / sigma if xi < 1e-9 else np.log1p(xi * x / sigma) / xi
    sur[s < u] = 0.0
    return sur[::-1], {"u": u, "xi": xi, "sigma": sigma,
                       "fondo": hi - lo, "cola_relevante": n - hi}


class SurpriseTruncator:
    """Corta una lista ordenada donde la sorpresa baja de ``threshold``.

    ``depth`` es cuántos de los primeros se modelan (el artículo usa los 200
    más cercanos). El método supone que la mayoría de esa lista es no
    relevante: en temas muy amplios, con muchos relevantes, el fondo queda
    contaminado y se seleccionan menos; es parte de lo que mide la evaluación.
    """

    def __init__(self, threshold: float = 3.0, depth: int = 200) -> None:
        self.threshold = threshold
        self.depth = depth

    def cut(self, ranked: list[tuple[str, float]]) -> tuple[list[tuple[str, float]], dict[str, float]]:
        """``(lista cortada, {artículo: sorpresa})`` para ``ranked`` (de mayor a menor)."""
        head = ranked[:self.depth]
        sur, _ = surprise_scores([score for _, score in head])
        surprise = {aid: float(v) for (aid, _), v in zip(head, sur)}
        kept = [(aid, score) for aid, score in head if surprise[aid] >= self.threshold]
        return kept, surprise
