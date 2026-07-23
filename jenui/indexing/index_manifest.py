"""Registro de con qué se construyó el índice."""
from __future__ import annotations

import json
from pathlib import Path

from jenui.providers.embedding_provider import EmbeddingProvider
from jenui.providers.llm_provider import LLMProvider


class IndexManifest:
    """Deja constancia de los proveedores con los que se construyó el índice.

    Sirve para detectar incompatibilidades antes de corromper nada:

    * **Embeddings** — determinan la dimensión de los vectores. Mezclar dos
      modelos distintos rompe el índice, así que se aborta.
    * **LLM** — cambiarlo no rompe nada, pero los nombres de entidad pueden
      variar de estilo y fragmentar el grafo, así que solo se avisa.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save(self, embeddings: EmbeddingProvider | None = None,
             llm: LLMProvider | None = None) -> None:
        data = self.load()
        if embeddings:
            data["embed"] = embeddings.fingerprint()
        if llm:
            data["llm"] = llm.fingerprint()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def check_embeddings(self, provider: EmbeddingProvider) -> None:
        """Aborta si el índice se construyó con otros embeddings."""
        recorded = self.load().get("embed")
        if not recorded:
            return
        current = provider.fingerprint()
        if (recorded.get("dim") != current["dim"]
                or recorded.get("model") != current["model"]):
            raise SystemExit(
                f"\n[ERROR] El índice se construyó con embeddings "
                f"{recorded.get('provider')}/{recorded.get('model')} "
                f"(dim {recorded.get('dim')}), pero ahora pides "
                f"{current['provider']}/{current['model']} (dim {current['dim']}).\n"
                f"Cambiar de embeddings obliga a reconstruir: usa --rebuild.\n"
            )

    def warn_if_llm_changed(self, provider: LLMProvider) -> str | None:
        """Avisa (sin abortar) si el grafo se construyó con otro LLM."""
        recorded = self.load().get("llm")
        if not recorded:
            return None
        current = provider.fingerprint()
        if recorded.get("model") == current["model"]:
            return None
        return (
            f"[AVISO] El grafo se construyó con {recorded.get('provider')}/"
            f"{recorded.get('model')} y ahora usas {current['provider']}/"
            f"{current['model']}.\n"
            f"         No es un error, pero los nombres de entidad pueden variar "
            f"de estilo y no fusionarse con los existentes.\n"
            f"         Ejecuta merge_aliases.py al terminar para consolidarlos."
        )
