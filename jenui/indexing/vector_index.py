"""Índice vectorial de texto completo."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class ChunkHit:
    """Un fragmento recuperado, con su artículo de origen y su similitud."""

    article_id: str
    text: str
    score: float


class VectorIndex:
    """Índice de fragmentos: matriz de vectores + metadatos paralelos.

    Los vectores se guardan **normalizados a norma 1**, de forma que el coseno
    es un simple producto escalar y toda la consulta se resuelve con un único
    producto matricial.

    A esta escala (decenas de miles de fragmentos) no compensa un índice
    aproximado tipo FAISS: la búsqueda exacta tarda milisegundos y evita una
    dependencia pesada.
    """

    def __init__(self, vectors: np.ndarray | None = None,
                 meta: list[dict] | None = None) -> None:
        self.vectors = vectors
        self.meta = meta or []

    # ------------------------------------------------------------------ estado
    @property
    def is_ready(self) -> bool:
        return self.vectors is not None and len(self.meta) > 0

    @property
    def dim(self) -> int | None:
        return int(self.vectors.shape[1]) if self.vectors is not None else None

    @property
    def n_chunks(self) -> int:
        return len(self.meta)

    def indexed_article_ids(self) -> set[str]:
        return {m["article_id"] for m in self.meta}

    # ------------------------------------------------------------ persistencia
    @classmethod
    def load(cls, vectors_path: Path, meta_path: Path) -> "VectorIndex":
        if not (vectors_path.exists() and meta_path.exists()):
            return cls()
        return cls(
            vectors=np.load(vectors_path),
            meta=json.loads(meta_path.read_text(encoding="utf-8")),
        )

    def save(self, vectors_path: Path, meta_path: Path) -> None:
        if self.vectors is None:
            return
        vectors_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(vectors_path, self.vectors)
        meta_path.write_text(
            json.dumps(self.meta, ensure_ascii=False), encoding="utf-8"
        )

    def extend(self, vectors: np.ndarray, meta: list[dict]) -> None:
        """Añade fragmentos nuevos conservando los existentes."""
        if self.vectors is None or self.vectors.size == 0:
            self.vectors, self.meta = vectors, list(meta)
            return
        if vectors.shape[1] != self.vectors.shape[1]:
            raise ValueError(
                f"Dimensión incompatible: índice {self.vectors.shape[1]}, "
                f"nuevos {vectors.shape[1]}"
            )
        self.vectors = np.concatenate([self.vectors, vectors], axis=0)
        self.meta = self.meta + list(meta)

    # ------------------------------------------------------------------ consulta
    def score_articles(self, query_vector: np.ndarray, pooling: str = "hybrid",
                       k: int = 3, alpha: float = 0.5) -> dict[str, ChunkHit]:
        """Puntúa cada artículo agregando las similitudes de sus fragmentos.

        El *pooling* decide cómo se combina un artículo troceado en un solo
        número:

        * ``max`` — el mejor fragmento. Máximo recall (un artículo relevante en
          una sola sección puntúa alto), pero no distingue "trata el tema a
          fondo" de "lo menciona de refilón".
        * ``mean_topk`` — media de los ``k`` mejores fragmentos. Premia la
          cobertura: un artículo focal, con varios fragmentos afines, gana a otro
          con un único pico.
        * ``hybrid`` — ``alpha·max + (1-alpha)·media_topk``. Conserva el recall
          del máximo y añade la señal de profundidad. Es el equilibrio por
          defecto.

        Devuelve, por artículo, la puntuación agregada y el texto de su **mejor**
        fragmento (para contexto).
        """
        if not self.is_ready:
            return {}
        similarities = self.vectors @ query_vector
        by_article: dict[str, list[tuple[float, str]]] = {}
        for position, entry in enumerate(self.meta):
            by_article.setdefault(entry["article_id"], []).append(
                (float(similarities[position]), entry.get("text", ""))
            )

        results: dict[str, ChunkHit] = {}
        for article_id, fragments in by_article.items():
            fragments.sort(key=lambda item: item[0], reverse=True)
            scores = [score for score, _ in fragments]
            best_score, best_text = fragments[0]
            results[article_id] = ChunkHit(
                article_id, best_text, self._pool(scores, pooling, k, alpha, best_score)
            )
        return results

    # alias retrocompatible: pooling por máximo
    def best_per_article(self, query_vector: np.ndarray) -> dict[str, ChunkHit]:
        return self.score_articles(query_vector, pooling="max")

    def article_scores_detail(self, query_vector: np.ndarray, pooling: str,
                              k: int, alpha: float, top_fragments: int = 5
                              ) -> list[dict]:
        """Detalle por artículo para depuración: score agregado, mejor fragmento,
        las mejores similitudes de fragmento y cuántos hay. Ordenado de mejor a
        peor por el score agregado."""
        if not self.is_ready:
            return []
        similarities = self.vectors @ query_vector
        by_article: dict[str, list[float]] = {}
        for position, entry in enumerate(self.meta):
            by_article.setdefault(entry["article_id"], []).append(
                float(similarities[position])
            )
        detail = []
        for article_id, scores in by_article.items():
            scores.sort(reverse=True)
            detail.append({
                "article_id": article_id,
                "score": self._pool(scores, pooling, k, alpha, scores[0]),
                "best": scores[0],
                "top_fragments": [round(s, 4) for s in scores[:top_fragments]],
                "n_fragments": len(scores),
            })
        detail.sort(key=lambda d: d["score"], reverse=True)
        return detail

    @staticmethod
    def _pool(scores: list[float], pooling: str, k: int, alpha: float,
              best: float) -> float:
        if pooling == "max" or len(scores) == 1:
            return best
        top = scores[:max(1, k)]
        mean_top = sum(top) / len(top)
        if pooling == "mean_topk":
            return mean_top
        return alpha * best + (1.0 - alpha) * mean_top   # hybrid

    @staticmethod
    def normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms
