"""Entidad de dominio: un resultado de búsqueda."""
from __future__ import annotations

from dataclasses import dataclass, field

from jenui.domain.article import Article


@dataclass
class SearchResult:
    """Un artículo devuelto por una búsqueda, con su puntuación y su porqué.

    ``shared_concepts`` explica *por qué* aparece: son los conceptos del grafo
    que comparte con los mejores resultados textuales. Va vacío cuando el
    artículo entró por similitud de texto y no por expansión del grafo.
    """

    article: Article
    score: float
    text_score: float
    shared_concepts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        a = self.article
        return {
            "id": a.id,
            "title": a.title or a.id,
            "authors": a.authors,
            "year": a.year,
            "abstract": a.abstract,
            "keywords": a.keywords,
            "category": a.category,
            "score": round(float(self.score), 4),
            "text_score": round(float(self.text_score), 4),
            "shared_concepts": self.shared_concepts,
            "pdf": f"/pdf/{a.filename or a.id + '.pdf'}",
            "cite_key": a.cite_key,
            "bibtex": a.bibtex,
        }
