"""LLM vía la API de OpenAI."""
from __future__ import annotations

from jenui.config.settings import Settings
from jenui.providers.llm_provider import LLMProvider


class OpenAILLMProvider(LLMProvider):
    """LLM por API de OpenAI.

    Los modelos de esta familia respetan bastante mejor la ontología pedida en
    ``graph.entity_types`` que un modelo local pequeño, que es justo de lo que
    depende la calidad del grafo.

    ``llm_max_async`` puede subirse bastante más que en local (la GPU deja de
    ser el cuello de botella), pero vigila el límite de tokens por minuto de tu
    cuenta.
    """

    name = "openai"
    DEFAULT_MODEL = "gpt-5.4-nano"

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "Falta OPENAI_API_KEY para el proveedor de LLM 'openai'. "
                "Ponla en el fichero .env o expórtala en el entorno."
            )
        super().__init__(model=settings.llm_model or self.DEFAULT_MODEL)
        self._api_key = settings.openai_api_key
        self._base_url = settings.openai_base_url
        self._max_async = settings.graph.get("llm_max_async", 4)

    def as_lightrag_kwargs(self) -> dict:
        from lightrag.llm.openai import openai_complete

        return {
            "llm_model_func": openai_complete,
            "llm_model_name": self.model,
            "llm_model_max_async": self._max_async,
            "llm_model_kwargs": {
                "api_key": self._api_key,
                "base_url": self._base_url,
            },
        }
