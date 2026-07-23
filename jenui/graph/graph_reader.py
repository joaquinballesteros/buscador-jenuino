"""Lectura del grafo generado por LightRAG."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from jenui.graph.entity_type_filter import EntityTypeFilter

NAMESPACE = {"g": "http://graphml.graphdrawing.org/xmlns"}


@dataclass
class RawGraph:
    """Entidades leídas del GraphML, antes de consolidar variantes."""

    entity_to_articles: dict[str, set[str]] = field(default_factory=dict)
    discarded: int = 0


class GraphReader:
    """Lee el GraphML de LightRAG y lo reduce a *entidad → artículos*.

    Se leen los ficheros directamente en lugar de usar el motor de consulta de
    LightRAG a propósito: su consulta hace una llamada al LLM por búsqueda, lo
    que añadiría coste y segundos de latencia. Aquí solo interesa la estructura
    del grafo, que es un fichero XML.

    Cada nodo del GraphML guarda ``source_id`` con los fragmentos de los que se
    extrajo; el almacén de fragmentos dice a qué artículo pertenece cada uno.
    """

    def __init__(self, graphml_path: Path, chunks_kv_path: Path,
                 entity_filter: EntityTypeFilter) -> None:
        self._graphml = graphml_path
        self._chunks_kv = chunks_kv_path
        self._filter = entity_filter

    def exists(self) -> bool:
        return self._graphml.exists() and self._chunks_kv.exists()

    def mtime(self) -> float:
        return self._graphml.stat().st_mtime if self._graphml.exists() else 0.0

    def read(self) -> RawGraph:
        if not self.exists():
            return RawGraph()

        chunk_to_article = self._chunk_to_article()
        root = ET.parse(self._graphml).getroot()
        key_source, key_type = self._attribute_keys(root)
        graph = root.find("g:graph", NAMESPACE)
        if graph is None:
            return RawGraph()

        entity_to_articles: dict[str, set[str]] = defaultdict(set)
        discarded = 0
        for node in graph.findall("g:node", NAMESPACE):
            entity = (node.get("id") or "").strip().strip('"')
            if not entity:
                continue
            source_ids, entity_type = "", ""
            for data in node.findall("g:data", NAMESPACE):
                key = data.get("key")
                if key == key_source:
                    source_ids = data.text or ""
                elif key_type and key == key_type:
                    entity_type = data.text or ""
            if self._filter.is_discarded(entity_type):
                discarded += 1
                continue
            for chunk_id in source_ids.replace("<SEP>", "|").split("|"):
                article = chunk_to_article.get(chunk_id.strip())
                if article:
                    entity_to_articles[entity].add(article)

        return RawGraph(dict(entity_to_articles), discarded)

    # ------------------------------------------------------------------ interno
    def _chunk_to_article(self) -> dict[str, str]:
        chunks = json.loads(self._chunks_kv.read_text(encoding="utf-8"))
        return {cid: c.get("full_doc_id") for cid, c in chunks.items()}

    @staticmethod
    def _attribute_keys(root) -> tuple[str | None, str | None]:
        """El GraphML declara los atributos con identificadores (d0, d1…)."""
        key_source = key_type = None
        for key in root.findall("g:key", NAMESPACE):
            name = key.get("attr.name")
            if name in ("source_id", "source_ids"):
                key_source = key.get("id")
            elif name == "entity_type":
                key_type = key.get("id")
        return key_source, key_type
