"""Construcción del índice de vectores de concepto (nombre + descripción)."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

from jenui.config.settings import Settings
from jenui.graph.entity_type_filter import EntityTypeFilter
from jenui.graph.graph_reader import NAMESPACE
from jenui.providers.provider_factory import ProviderFactory

DESC_CHARS = 320


@dataclass
class ConceptBuildReport:
    concepts: int
    seconds: float


class ConceptEmbeddingBuilder:
    """Genera ``data/concept_vectors.npz`` embebiendo *nombre + descripción*.

    Embeber solo el nombre ("Rúbrica") mezcla términos educativos cortos en la
    misma zona del espacio. Añadir la descripción que LightRAG guardó por
    entidad ("Rúbrica: instrumento de evaluación...") los separa mucho mejor.

    Guarda también el **vector medio**, que :class:`ConceptIndex` resta para
    contrarrestar la anisotropía de los embeddings (todos apuntan a una zona
    común, lo que infla las similitudes).

    Local y sin LLM: solo cuesta tiempo de embeddings (una vez).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._paths = settings.paths
        self._embeddings = ProviderFactory(settings).embeddings()
        self._filter = EntityTypeFilter(settings.search.get("tipos_entidad_descartados"))

    def build(self, batch_size: int = 32, verbose: bool = True) -> ConceptBuildReport:
        names, texts = self._read_concepts()
        if verbose:
            print(f"Conceptos a embeber: {len(names)} "
                  f"(nombre + descripción) con {self._embeddings.name}/"
                  f"{self._embeddings.model}")

        vectors = np.zeros((len(texts), self._embeddings.dim), dtype=np.float32)
        started = time.time()
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            vectors[start:start + len(batch)] = self._embeddings.embed(batch)
            if verbose and (start // batch_size) % 20 == 0:
                done = min(start + batch_size, len(texts))
                rate = done / max(time.time() - started, 1e-6)
                print(f"  {done}/{len(texts)}  ({rate:.1f} emb/s)")

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors /= norms
        mean = vectors.mean(axis=0)

        self._paths.data_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self._paths.data_dir / "concept_vectors.npz",
            names=np.array(names), vectors=vectors, mean=mean,
        )
        return ConceptBuildReport(concepts=len(names), seconds=time.time() - started)

    # ------------------------------------------------------------------ interno
    def _read_concepts(self) -> tuple[list[str], list[str]]:
        """Lee (nombre, 'nombre. descripción') de cada entidad no-metadato."""
        graphml = self._paths.graphml_file
        if not graphml.exists():
            raise SystemExit("No hay grafo todavía. Ejecuta build_graph.py primero.")
        root = ET.parse(graphml).getroot()
        key_type, key_desc = None, None
        for key in root.findall("g:key", NAMESPACE):
            if key.get("attr.name") == "entity_type":
                key_type = key.get("id")
            elif key.get("attr.name") == "description":
                key_desc = key.get("id")

        names, texts = [], []
        for node in root.find("g:graph", NAMESPACE).findall("g:node", NAMESPACE):
            name = (node.get("id") or "").strip().strip('"')
            if not name:
                continue
            entity_type, description = "", ""
            for data in node.findall("g:data", NAMESPACE):
                if key_type and data.get("key") == key_type:
                    entity_type = data.text or ""
                elif key_desc and data.get("key") == key_desc:
                    description = data.text or ""
            if self._filter.is_discarded(entity_type):
                continue
            names.append(name)
            snippet = (description or "")[:DESC_CHARS]
            texts.append(f"{name}. {snippet}".strip())
        return names, texts
