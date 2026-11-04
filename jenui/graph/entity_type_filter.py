"""Filtrado de entidades que son metadatos."""
from __future__ import annotations

import re
import unicodedata

#: Tipos que designan metadatos y no relacionan artículos por tema.
DEFAULT_DISCARDED_TYPES = [
    "person", "persona", "autor", "author", "people",
    "organization", "organizacion", "institucion", "organisation", "empresa",
    "location", "ubicacion", "lugar", "geo", "place",
    "event", "evento", "date", "fecha",
    "unknown", "other", "otro", "obra", "obraliteraria", "publicacion",
    "documento", "articulo", "content",
]


class EntityTypeFilter:
    """Descarta las entidades cuyo tipo es un metadato.

    Es una **red de seguridad** frente a la ontología pedida al modelo: aunque
    se le indique qué tipos queremos, los modelos pequeños se desvían y los
    grandes dejan un residuo en la categoría ``Other`` (autores, universidades,
    nombres de las propias actas). Filtrar aquí garantiza el resultado sin
    depender de que el modelo obedezca.

    La comparación normaliza el tipo, de modo que ``Organización``,
    ``organizacion`` y ``ORGANIZATION`` se descartan por igual.
    """

    def __init__(self, discarded: list[str] | None = None,
                 name_patterns: list[str] | None = None) -> None:
        source = discarded if discarded is not None else DEFAULT_DISCARDED_TYPES
        self._discarded = {self.normalize(t) for t in source}
        self._name_patterns = [re.compile(p) for p in (name_patterns or [])]

    @classmethod
    def from_settings(cls, settings) -> "EntityTypeFilter":
        """Tipos (``search.tipos_entidad_descartados``) y nombres
        (``search.patrones_entidad_descartados``) que se descartan."""
        return cls(settings.search.get("tipos_entidad_descartados"),
                   settings.search.get("patrones_entidad_descartados"))

    @staticmethod
    def normalize(entity_type: str) -> str:
        text = "".join(
            c for c in unicodedata.normalize("NFKD", entity_type or "")
            if not unicodedata.combining(c)
        )
        return text.lower().replace(" ", "").replace("_", "").replace("-", "")

    def is_discarded(self, entity_type: str, name: str | None = None) -> bool:
        """Por tipo y, si se da, por nombre.

        El nombre importa porque el LLM a veces clasifica una institución con
        un tipo de la ontología ("Universidad de Alicante" como contexto): sin
        este filtro, dos artículos se relacionaban por ser de la misma
        universidad, no por tratar el mismo tema.
        """
        if self.normalize(entity_type) in self._discarded:
            return True
        if name and self._name_patterns:
            plain = "".join(c for c in unicodedata.normalize("NFKD", name.lower())
                            if not unicodedata.combining(c)).strip()
            return any(p.search(plain) for p in self._name_patterns)
        return False

    def __contains__(self, entity_type: str) -> bool:
        return self.is_discarded(entity_type)
