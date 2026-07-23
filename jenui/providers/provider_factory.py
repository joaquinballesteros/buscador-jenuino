"""Fábrica que resuelve la estrategia concreta a partir de la configuración."""
from __future__ import annotations

from jenui.config.settings import Settings
from jenui.providers.anthropic_llm_provider import AnthropicLLMProvider
from jenui.providers.embedding_provider import EmbeddingProvider
from jenui.providers.llm_provider import LLMProvider
from jenui.providers.ollama_embedding_provider import OllamaEmbeddingProvider
from jenui.providers.ollama_llm_provider import OllamaLLMProvider
from jenui.providers.openai_embedding_provider import OpenAIEmbeddingProvider
from jenui.providers.openai_llm_provider import OpenAILLMProvider


class ProviderFactory:
    """Crea proveedores de LLM y embeddings según ``config.json``.

    Es el único punto donde se conocen las implementaciones concretas: el resto
    del sistema trabaja contra las interfaces :class:`EmbeddingProvider` y
    :class:`LLMProvider`.

    Para dar de alta un proveedor nuevo, basta con añadirlo al registro
    correspondiente::

        ProviderFactory.EMBEDDINGS["cohere"] = CohereEmbeddingProvider
    """

    EMBEDDINGS: dict[str, type[EmbeddingProvider]] = {
        "ollama": OllamaEmbeddingProvider,
        "openai": OpenAIEmbeddingProvider,
    }

    LLMS: dict[str, type[LLMProvider]] = {
        "ollama": OllamaLLMProvider,
        "openai": OpenAILLMProvider,
        "anthropic": AnthropicLLMProvider,
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def embeddings(self, name: str | None = None) -> EmbeddingProvider:
        key = (name or self._settings.embedding_provider).lower()
        if key not in self.EMBEDDINGS:
            raise ValueError(
                f"Proveedor de embeddings desconocido: {key!r}. "
                f"Opciones: {sorted(self.EMBEDDINGS)}"
            )
        return self.EMBEDDINGS[key](self._settings)

    def llm(self, name: str | None = None) -> LLMProvider:
        key = (name or self._settings.llm_provider).lower()
        if key not in self.LLMS:
            raise ValueError(
                f"Proveedor de LLM desconocido: {key!r}. Opciones: {sorted(self.LLMS)}"
            )
        return self.LLMS[key](self._settings)
