"""Índice de vectores de concepto, para juzgar su relevancia frente a una consulta."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from jenui.config.paths import Paths
from jenui.graph.alias_resolver import AliasResolver


class ConceptIndex:
    """Da un vector a cada concepto y mide su afinidad con una consulta.

    Dos técnicas para que los términos educativos cortos no se agolpen:

    * **Centrado** — resta el vector medio antes de comparar. Los embeddings son
      anisótropos (todos apuntan a una zona común), lo que infla artificialmente
      las similitudes; quitar la media las separa mucho.
    * **Descripción** — si existe ``concept_vectors.npz`` (lo genera
      ``build_concepts.py`` embebiendo *nombre + descripción*), lo prefiere al
      índice de solo-nombres, porque la descripción desambigua el concepto.

    Degrada con elegancia: usa el mejor artefacto disponible y, si no hay
    ninguno, se desactiva (el buscador funciona sin filtro de relevancia).
    Se indexa por **nombre normalizado** para tolerar variantes de mayúsculas,
    acentos y puntuación.
    """

    def __init__(self, paths: Paths) -> None:
        self._by_name: dict[str, np.ndarray] = {}
        self._mean = np.zeros(1, dtype=np.float32)
        self.source = "none"
        self._load(paths)

    def _load(self, paths: Paths) -> None:
        # preferimos el índice enriquecido con descripciones
        enriched = paths.data_dir / "concept_vectors.npz"
        names_only = paths.data_dir / "entity_name_vectors.npz"
        if enriched.exists():
            self._load_file(enriched, source="descripción")
        elif names_only.exists():
            self._load_file(names_only, source="solo-nombre")

    def _load_file(self, path: Path, source: str) -> None:
        try:
            data = np.load(path, allow_pickle=False)
            names = data["names"]
            vectors = data["vectors"].astype(np.float32)
            mean = data["mean"].astype(np.float32) if "mean" in data else vectors.mean(0)
        except (OSError, KeyError, ValueError):
            return
        self._mean = mean
        centered = self._center(vectors)
        for name, vector in zip(names, centered):
            self._by_name.setdefault(AliasResolver.normalize(str(name)), vector)
        self.source = source

    def _center(self, vectors: np.ndarray) -> np.ndarray:
        """Resta la media y renormaliza (coseno en el espacio centrado)."""
        centered = vectors - self._mean
        norms = np.linalg.norm(centered, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return centered / norms

    @property
    def is_available(self) -> bool:
        return bool(self._by_name)

    def center_query(self, query_vector: np.ndarray) -> np.ndarray:
        """Lleva la consulta al mismo espacio centrado que los conceptos."""
        return self._center(query_vector.reshape(1, -1))[0]

    def relevances(self, concepts, query_vector: np.ndarray) -> dict[str, float]:
        """Afinidad de cada concepto con la consulta (solo los que tienen vector)."""
        centered_query = self.center_query(query_vector)
        scores: dict[str, float] = {}
        for concept in concepts:
            vector = self._by_name.get(AliasResolver.normalize(concept))
            if vector is not None:
                scores[concept] = float(vector @ centered_query)
        return scores
