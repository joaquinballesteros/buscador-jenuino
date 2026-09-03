"""LLM local vía Ollama."""
from __future__ import annotations

from jenui.config.settings import Settings
from jenui.providers.llm_provider import LLMProvider


class OllamaLLMProvider(LLMProvider):
    """LLM en local con Ollama: sin coste, a cambio de tiempo.

    Aviso de dimensionamiento: el modelo debe caber en RAM/VRAM junto con su
    contexto. En una máquina de 16 GB, un modelo de 14B con ``num_ctx`` de 16k
    se va a ~15 GB y provoca *swapping*, dejando el indexado inservible. Con esa
    memoria, quédate en la franja de 7-8B.
    """

    name = "ollama"
    DEFAULT_MODEL = "qwen2.5:7b-instruct"

    def __init__(self, settings: Settings) -> None:
        super().__init__(model=settings.llm_model or self.DEFAULT_MODEL)
        self._host = settings.ollama_host
        self._num_ctx = settings.ollama_num_ctx
        self._max_async = settings.graph.get("llm_max_async", 2)

    def as_lightrag_kwargs(self) -> dict:
        from lightrag.llm.ollama import ollama_model_complete

        return {
            "llm_model_func": ollama_model_complete,
            "llm_model_name": self.model,
            "llm_model_max_async": self._max_async,
            "llm_model_kwargs": {
                "host": self._host,
                "options": {"num_ctx": self._num_ctx},
                "timeout": 600,
                "think": False,
            },
        }
