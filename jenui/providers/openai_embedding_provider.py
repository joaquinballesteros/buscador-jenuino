"""Embeddings vía la API de OpenAI."""
from __future__ import annotations

import numpy as np

from jenui.config.settings import Settings
from jenui.providers.embedding_provider import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embeddings por API de OpenAI.

    Ojo: cambiar de proveedor de embeddings cambia la dimensión de los vectores
    y obliga a reconstruir el índice y el grafo.
    """

    name = "openai"
    DEFAULT_MODEL = "text-embedding-3-small"
    KNOWN_DIMS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "Falta OPENAI_API_KEY para el proveedor de embeddings 'openai'. "
                "Ponla en el fichero .env o expórtala en el entorno."
            )
        model = settings.embedding_model or self.DEFAULT_MODEL
        dim = settings.embedding_dim_override or self.KNOWN_DIMS.get(model, 1536)
        super().__init__(model=model, dim=dim)
        self._api_key = settings.openai_api_key
        self._base_url = settings.openai_base_url

    def embed(self, texts: list[str]) -> np.ndarray:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        response = client.embeddings.create(model=self.model, input=texts)
        return np.asarray([d.embedding for d in response.data], dtype=np.float32)

    def as_lightrag_func(self):
        from lightrag.llm.openai import openai_embed
        from lightrag.utils import EmbeddingFunc

        return EmbeddingFunc(
            embedding_dim=self.dim,
            max_token_size=self.max_tokens,
            func=lambda texts: openai_embed(
                texts, model=self.model,
                api_key=self._api_key, base_url=self._base_url,
            ),
        )
