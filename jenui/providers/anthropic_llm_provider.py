"""LLM vía la API de Anthropic."""
from __future__ import annotations

from jenui.config.settings import Settings
from jenui.providers.llm_provider import LLMProvider


class AnthropicLLMProvider(LLMProvider):
    """LLM por API de Anthropic.

    Anthropic no ofrece embeddings, así que este proveedor se combina con
    embeddings de otro sitio (Ollama en local, u OpenAI). Es una configuración
    perfectamente válida: el LLM y los embeddings se eligen por separado.
    """

    name = "anthropic"
    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "Falta ANTHROPIC_API_KEY para el proveedor de LLM 'anthropic'. "
                "Ponla en el fichero .env o expórtala en el entorno."
            )
        super().__init__(model=settings.llm_model or self.DEFAULT_MODEL)
        self._api_key = settings.anthropic_api_key
        self._max_async = settings.graph.get("llm_max_async", 4)

    def as_lightrag_kwargs(self) -> dict:
        from lightrag.llm.anthropic import anthropic_complete

        return {
            "llm_model_func": anthropic_complete,
            "llm_model_name": self.model,
            "llm_model_max_async": self._max_async,
            "llm_model_kwargs": {"api_key": self._api_key},
        }
