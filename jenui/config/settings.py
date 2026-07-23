"""Carga de la configuración del sistema."""
from __future__ import annotations

import json
import os
from typing import Any

from jenui.config.paths import Paths


class Settings:
    """Configuración del sistema, leída de ``config.json``.

    Prioridad: **variable de entorno > config.json > valor por defecto**.

    Las claves de API se leen *solo* del entorno (o del fichero ``.env``, que no
    se versiona); nunca de ``config.json``, que sí va al repositorio.

    Uso::

        settings = Settings.load()
        settings.graph["entity_types"]
        settings.llm_provider
    """

    def __init__(self, raw: dict, paths: Paths) -> None:
        self._raw = raw
        self.paths = paths

    # ------------------------------------------------------------------ carga
    @classmethod
    def load(cls, paths: Paths | None = None) -> "Settings":
        paths = paths or Paths.default()
        cls._load_dotenv(paths)
        raw = cls._read_json(paths)
        paths.ensure_dirs()
        return cls(raw, paths)

    @staticmethod
    def _load_dotenv(paths: Paths) -> None:
        """Vuelca las claves de ``.env`` al entorno sin pisar lo ya definido."""
        if not paths.env_file.exists():
            return
        for line in paths.env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    @staticmethod
    def _read_json(paths: Paths) -> dict:
        if not paths.config_file.exists():
            return {}
        try:
            return json.loads(paths.config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[ERROR] config.json no es JSON válido: {exc}") from exc

    # ------------------------------------------------------------- acceso raw
    def get(self, path: str, default: Any = None, env: str | None = None,
            cast=None) -> Any:
        """Lee un valor por ruta con puntos, p. ej. ``providers.llm.model``."""
        if env and os.environ.get(env):
            value = os.environ[env]
            return cast(value) if cast else value
        node: Any = self._raw
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return default if node is None else node

    def section(self, name: str) -> dict:
        """Sección de ``config.json`` sin las claves de comentario (``_...``)."""
        node = self._raw.get(name, {})
        if not isinstance(node, dict):
            return {}
        return {k: v for k, v in node.items() if not k.startswith("_")}

    # ------------------------------------------------------------ proveedores
    @property
    def llm_provider(self) -> str:
        return str(self.get("providers.llm.provider", "ollama",
                            env="JENUI_LLM_PROVIDER")).lower()

    @property
    def llm_model(self) -> str | None:
        return self.get("providers.llm.model", None, env="JENUI_LLM_MODEL")

    @property
    def embedding_provider(self) -> str:
        return str(self.get("providers.embeddings.provider", "ollama",
                            env="JENUI_EMBED_PROVIDER")).lower()

    @property
    def embedding_model(self) -> str | None:
        return self.get("providers.embeddings.model", None, env="JENUI_EMBED_MODEL")

    @property
    def embedding_dim_override(self) -> int | None:
        return self.get("providers.embeddings.dim", None)

    @property
    def ollama_host(self) -> str:
        return self.get("providers.ollama.host", "http://localhost:11434",
                        env="OLLAMA_HOST")

    @property
    def ollama_num_ctx(self) -> int:
        return int(self.get("providers.ollama.num_ctx", 16384,
                            env="JENUI_CTX", cast=int))

    # ------------------------------------------------------------------ claves
    @property
    def openai_api_key(self) -> str | None:
        return os.environ.get("OPENAI_API_KEY")

    @property
    def openai_base_url(self) -> str | None:
        return os.environ.get("OPENAI_BASE_URL")

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY")

    # ---------------------------------------------------------------- secciones
    @property
    def graph(self) -> dict:
        return self.section("graph")

    @property
    def fulltext(self) -> dict:
        return self.section("fulltext")

    @property
    def search(self) -> dict:
        return self.section("search")
