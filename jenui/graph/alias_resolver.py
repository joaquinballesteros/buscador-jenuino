"""Consolidación de variantes que designan el mismo concepto."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConsolidatedGraph:
    """Grafo ya consolidado, listo para consultar."""

    entity_to_articles: dict[str, set[str]] = field(default_factory=dict)
    article_to_entities: dict[str, set[str]] = field(default_factory=dict)
    merged: int = 0


class AliasResolver:
    """Fusiona las entidades que nombran el mismo concepto.

    LightRAG fusiona entidades solo por **coincidencia exacta** de nombre (el
    identificador del nodo *es* el nombre), así que el mismo concepto acaba
    partido en varios nodos y deja de conectar artículos. Medido en este corpus,
    una sola pasada produjo ``Investigación-acción``, ``Investigación-Acción`` y
    ``Formación en Investigación-Acción`` por separado.

    Se resuelve en dos capas:

    1. **Textual** (siempre activa, gratis): normaliza mayúsculas, acentos,
       guiones y puntuación. Une las dos primeras variantes del ejemplo.
    2. **Semántica** (opcional): aplica el mapa que genera
       :class:`~jenui.graph.semantic_alias_builder.SemanticAliasBuilder`
       comparando embeddings de los nombres. Une la tercera, y casos como
       ``ABP`` ↔ ``Aprendizaje basado en proyectos``.
    """

    def __init__(self, aliases_path: Path | None = None) -> None:
        self._aliases_path = aliases_path
        self._semantic = self._load_semantic()

    def _load_semantic(self) -> dict[str, str]:
        if not self._aliases_path or not self._aliases_path.exists():
            return {}
        try:
            return json.loads(self._aliases_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def reload(self) -> None:
        self._semantic = self._load_semantic()

    @property
    def has_semantic_map(self) -> bool:
        return bool(self._semantic)

    @staticmethod
    def normalize(entity: str) -> str:
        """Clave de fusión textual: sin mayúsculas, acentos ni puntuación."""
        text = "".join(
            c for c in unicodedata.normalize("NFKD", entity or "")
            if not unicodedata.combining(c)
        )
        text = re.sub(r"[-_/]", " ", text.lower())
        text = re.sub(r"[^\w\s]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def group_key(self, entity: str) -> str:
        """Clave final: normalización textual, redirigida por el mapa semántico."""
        key = self.normalize(entity)
        return self._semantic.get(key, key)

    def consolidate(self, entity_to_articles: dict[str, set[str]]) -> ConsolidatedGraph:
        """Agrupa variantes y devuelve el grafo consolidado."""
        variants: dict[str, set[str]] = defaultdict(set)
        articles: dict[str, set[str]] = defaultdict(set)

        for entity, article_ids in entity_to_articles.items():
            key = self.group_key(entity)
            variants[key].add(entity)
            articles[key] |= article_ids

        merged = sum(len(v) - 1 for v in variants.values() if len(v) > 1)
        entity_map: dict[str, set[str]] = {}
        article_map: dict[str, set[str]] = defaultdict(set)

        for key, names in variants.items():
            canonical = self.pick_canonical(names)
            entity_map[canonical] = articles[key]
            for article_id in articles[key]:
                article_map[article_id].add(canonical)

        return ConsolidatedGraph(entity_map, dict(article_map), merged)

    @staticmethod
    def pick_canonical(names: set[str]) -> str:
        """Nombre representativo del grupo: el más largo (más informativo)."""
        return sorted(names, key=lambda name: (-len(name), name))[0]
