"""Interfaz de la estrategia de embeddings."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class EmbeddingProvider(ABC):
    """Estrategia para convertir texto en vectores.

    Toda implementación debe exponer:

    * ``dim``     — dimensión de los vectores (define la compatibilidad del índice)
    * ``embed``   — versión síncrona, usada al construir el índice y al consultar
    * ``as_lightrag_func`` — adaptador para LightRAG

    Añadir un proveedor nuevo consiste en heredar de esta clase y registrarlo en
    :class:`~jenui.providers.provider_factory.ProviderFactory`.
    """

    name: str = "base"
    max_tokens: int = 8192

    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Devuelve una matriz ``(len(texts), dim)`` de tipo float32."""

    @abstractmethod
    def as_lightrag_func(self):
        """Devuelve un ``lightrag.utils.EmbeddingFunc`` equivalente."""

    def embed_one(self, text: str) -> np.ndarray:
        """Embebe un texto y lo normaliza a norma 1 (para coseno vía producto)."""
        vector = self.embed([text])[0].astype(np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def fingerprint(self) -> dict:
        """Identidad del proveedor, para el manifiesto del índice."""
        return {"provider": self.name, "model": self.model, "dim": self.dim}

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}(model={self.model!r}, dim={self.dim})"
