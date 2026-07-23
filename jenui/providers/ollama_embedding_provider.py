"""Embeddings locales vía Ollama."""
from __future__ import annotations

import numpy as np

from jenui.config.settings import Settings
from jenui.providers.embedding_provider import EmbeddingProvider


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embeddings en local con Ollama. Sin coste y sin salida de datos.

    ``bge-m3`` es el modelo por defecto por su buen rendimiento en español.
    """

    name = "ollama"
    DEFAULT_MODEL = "bge-m3"
    KNOWN_DIMS = {"bge-m3": 1024, "nomic-embed-text": 768, "mxbai-embed-large": 1024}

    def __init__(self, settings: Settings) -> None:
        import ollama

        model = settings.embedding_model or self.DEFAULT_MODEL
        dim = settings.embedding_dim_override or self.KNOWN_DIMS.get(model, 1024)
        super().__init__(model=model, dim=dim)
        self._host = settings.ollama_host
        self._client = ollama.Client(host=self._host)

    def embed(self, texts: list[str]) -> np.ndarray:
        response = self._client.embed(model=self.model, input=texts)
        return np.asarray(response["embeddings"], dtype=np.float32)

    def as_lightrag_func(self):
        from lightrag.llm.ollama import ollama_embed
        from lightrag.utils import EmbeddingFunc

        return EmbeddingFunc(
            embedding_dim=self.dim,
            max_token_size=self.max_tokens,
            func=lambda texts: ollama_embed(
                texts, embed_model=self.model, host=self._host
            ),
        )
