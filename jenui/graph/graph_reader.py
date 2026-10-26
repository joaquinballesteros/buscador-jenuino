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
        entity_to_articles: dict[str, set[str]] = defaultdict(set)
        discarded = 0
        for entity, entity_type, chunk_ids in self._nodes():
            if self._filter.is_discarded(entity_type):
                discarded += 1
                continue
            for chunk_id in chunk_ids:
                article = chunk_to_article.get(chunk_id)
                if article:
                    entity_to_articles[entity].add(article)

        return RawGraph(dict(entity_to_articles), discarded)

    def read_occurrences(self) -> dict[str, dict[str, set[int]]]:
        """*entidad → artículo → posiciones de los fragmentos* donde aparece.

        Lo usa el análisis temporal para distinguir lo que un artículo *trata*
        de lo que solo *menciona*: con el texto completo, cada artículo acumula
        cientos de entidades, la mayoría citadas una sola vez de pasada.
        """
        if not self.exists():
            return {}
        chunks = self._chunks()
        occurrences: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for entity, entity_type, chunk_ids in self._nodes():
            if self._filter.is_discarded(entity_type):
                continue
            for chunk_id in chunk_ids:
                chunk = chunks.get(chunk_id)
                if chunk and chunk.get("full_doc_id"):
                    occurrences[entity][chunk["full_doc_id"]].add(
                        int(chunk.get("chunk_order_index", 0))
                    )
        return {e: dict(a) for e, a in occurrences.items()}

    def chunks_per_article(self) -> dict[str, int]:
        """Nº de fragmentos de cada artículo (1 si el grafo es de ámbito ``meta``)."""
        counts: dict[str, int] = defaultdict(int)
        for chunk in self._chunks().values():
            if chunk.get("full_doc_id"):
                counts[chunk["full_doc_id"]] += 1
        return dict(counts)

    # ------------------------------------------------------------------ interno
    def _nodes(self):
        """Recorre los nodos del GraphML: ``(entidad, tipo, ids de fragmento)``."""
        root = ET.parse(self._graphml).getroot()
        key_source, key_type = self._attribute_keys(root)
        graph = root.find("g:graph", NAMESPACE)
        if graph is None:
            return
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
            chunk_ids = [c.strip() for c in source_ids.replace("<SEP>", "|").split("|")]
            yield entity, entity_type, [c for c in chunk_ids if c]

    def _chunks(self) -> dict[str, dict]:
        return json.loads(self._chunks_kv.read_text(encoding="utf-8"))

    def _chunk_to_article(self) -> dict[str, str]:
        return {cid: c.get("full_doc_id") for cid, c in self._chunks().items()}

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
