"""Interfaz de la estrategia de LLM."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Estrategia para el LLM que extrae entidades y relaciones del grafo.

    El LLM **solo** se usa al construir el grafo. Las búsquedas no lo invocan
    nunca, de ahí que el buscador en uso no tenga coste ni latencia de API.

    Añadir un proveedor nuevo consiste en heredar de esta clase y registrarlo en
    :class:`~jenui.providers.provider_factory.ProviderFactory`.
    """

    name: str = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def as_lightrag_kwargs(self) -> dict:
        """Argumentos para ``LightRAG(**kwargs)``.

        Debe incluir ``llm_model_func``, ``llm_model_name``,
        ``llm_model_max_async`` y ``llm_model_kwargs``.
        """

    def fingerprint(self) -> dict:
        """Identidad del proveedor, para el manifiesto del índice."""
        return {"provider": self.name, "model": self.model}

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}(model={self.model!r})"
