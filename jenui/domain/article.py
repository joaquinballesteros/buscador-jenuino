"""Entidad de dominio: un artículo del congreso."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Article:
    """Un artículo del congreso, con su texto y sus metadatos ya limpios.

    Es la unidad que devuelve el buscador. Se construye combinando lo extraído
    del PDF con los metadatos de la ficha HTML (que son los fiables).
    """

    id: str
    filename: str
    year: int | None = None
    title: str = ""
    authors: str = ""
    abstract: str = ""
    keywords: str = ""
    category: str = ""
    venue: str = ""
    text: str = ""
    bibtex: str = ""
    cite_key: str = ""

    @property
    def n_chars(self) -> int:
        return len(self.text)

    @property
    def dense_header(self) -> str:
        """Título + palabras clave + resumen: la parte semánticamente densa.

        Se usa como primer fragmento del índice vectorial y como documento del
        grafo cuando el ámbito es ``meta``.
        """
        return " ".join(p for p in (self.title, self.keywords, self.abstract) if p)

    # ------------------------------------------------------------ persistencia
    def to_dict(self) -> dict:
        data = asdict(self)
        data["n_chars"] = self.n_chars
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
