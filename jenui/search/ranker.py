"""Combinación de las señales de ranking."""
from __future__ import annotations

from jenui.indexing.vector_index import ChunkHit


class Ranker:
    """Combina la similitud textual con el empuje del grafo.

    Son dos señales que responden a preguntas distintas:

    * la **textual** mide el parecido con la consulta;
    * la **del grafo** mide la cercanía conceptual a los mejores resultados.

    El peso del grafo es deliberadamente bajo: sirve para reordenar y para
    rescatar artículos afines que el texto no captó, no para mandar sobre la
    consulta del usuario. Ambos pesos se ajustan en ``config.json``.

    Para que los pesos signifiquen lo que dicen, las dos señales deben estar en
    la misma escala. El empuje del grafo se normaliza a 0-1, pero la similitud
    de los buenos resultados se concentra en unas centésimas (p. ej. 0,66-0,70
    en el top-15), así que sin normalizar el texto apenas separa y el grafo
    decide el orden. ``normalizacion`` lo corrige:

    * ``ninguna`` — similitud bruta (comportamiento histórico).
    * ``minmax`` — la similitud se reescala a 0-1 entre los ``candidatos``
      mejores por texto; los de fuera cuentan 0 de texto.
    * ``rrf`` — *Reciprocal Rank Fusion*: se combinan las **posiciones** en
      cada ranking, ``1/(k+posición)``, así que la escala deja de importar.

    En ``minmax`` y ``rrf`` la puntuación final se divide entre la suma de los
    pesos, de modo que queda en 0-1 (la web la muestra como porcentaje).
    """

    MODES = ("ninguna", "minmax", "rrf")

    def __init__(self, text_weight: float = 0.85, graph_weight: float = 0.15,
                 normalization: str = "ninguna", candidates: int = 50,
                 rrf_k: int = 60) -> None:
        if normalization not in self.MODES:
            raise ValueError(f"normalizacion desconocida: {normalization!r} "
                             f"(opciones: {', '.join(self.MODES)})")
        self._text_weight = text_weight
        self._graph_weight = graph_weight
        self._normalization = normalization
        self._candidates = max(2, candidates)
        self._rrf_k = rrf_k

    @classmethod
    def from_config(cls, config: dict) -> "Ranker":
        return cls(
            text_weight=config.get("peso_texto", 0.85),
            graph_weight=config.get("peso_grafo", 0.15),
            normalization=config.get("normalizacion", "ninguna"),
            candidates=config.get("candidatos_normalizacion", 50),
            rrf_k=config.get("rrf_k", 60),
        )

    def signals(self, text_hits: dict[str, ChunkHit],
                graph_weights: dict[str, float]) -> dict[str, tuple[float, float]]:
        """``(texto, grafo)`` de cada candidato, ya en la escala que se pondera."""
        ids = set(text_hits) | set(graph_weights)
        if self._normalization == "rrf":
            text_rank = self._positions({a: h.score for a, h in text_hits.items()})
            graph_rank = self._positions({a: w for a, w in graph_weights.items() if w > 0})
            return {a: (self._rrf(text_rank.get(a)), self._rrf(graph_rank.get(a)))
                    for a in ids}

        max_weight = max(graph_weights.values()) if graph_weights else 1.0
        graph = {a: graph_weights.get(a, 0.0) / max_weight for a in ids}
        text = {a: text_hits[a].score if a in text_hits else 0.0 for a in ids}
        if self._normalization == "minmax":
            text = self._min_max(text)
        return {a: (text[a], graph[a]) for a in ids}

    def rank(self, text_hits: dict[str, ChunkHit], graph_weights: dict[str, float],
             top_k: int) -> list[tuple[str, float]]:
        """Devuelve ``(article_id, score)`` ordenado de mayor a menor."""
        scale = 1.0
        if self._normalization != "ninguna":
            scale = (self._text_weight + self._graph_weight) or 1.0
        scores = {
            article_id: (self._text_weight * text + self._graph_weight * graph) / scale
            for article_id, (text, graph) in self.signals(text_hits, graph_weights).items()
        }
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]

    # ------------------------------------------------------------------ interno
    def _min_max(self, text: dict[str, float]) -> dict[str, float]:
        """Reescala a 0-1 entre los ``candidates`` mejores; el resto, 0."""
        pool = sorted(text.values(), reverse=True)[:self._candidates]
        if not pool:
            return text
        high, low = pool[0], pool[-1]
        span = high - low
        if span <= 0:
            return {a: 1.0 if s >= high else 0.0 for a, s in text.items()}
        return {a: min(1.0, max(0.0, (s - low) / span)) for a, s in text.items()}

    @staticmethod
    def _positions(scores: dict[str, float]) -> dict[str, int]:
        ordered = sorted(scores, key=scores.get, reverse=True)
        return {article_id: pos for pos, article_id in enumerate(ordered, 1)}

    def _rrf(self, position: int | None) -> float:
        """``1/(k+pos)`` reescalado para que el primero valga 1."""
        if position is None:
            return 0.0
        return (self._rrf_k + 1) / (self._rrf_k + position)
