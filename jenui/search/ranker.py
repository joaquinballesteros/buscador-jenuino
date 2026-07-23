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
    """

    def __init__(self, text_weight: float = 0.85, graph_weight: float = 0.15) -> None:
        self._text_weight = text_weight
        self._graph_weight = graph_weight

    def rank(self, text_hits: dict[str, ChunkHit], graph_weights: dict[str, float],
             top_k: int) -> list[tuple[str, float]]:
        """Devuelve ``(article_id, score)`` ordenado de mayor a menor."""
        max_weight = max(graph_weights.values()) if graph_weights else 1.0
        scores: dict[str, float] = {}
        for article_id in set(text_hits) | set(graph_weights):
            text_score = text_hits[article_id].score if article_id in text_hits else 0.0
            graph_score = graph_weights.get(article_id, 0.0) / max_weight
            scores[article_id] = (
                self._text_weight * text_score + self._graph_weight * graph_score
            )
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
