"""Rutas del proyecto."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Rutas del proyecto, derivadas de la raíz.

    Se agrupan aquí para que ningún módulo construya rutas a mano y para poder
    apuntar a otro directorio en tests.
    """

    root: Path
    #: Almacén de LightRAG alternativo (por defecto, ``rag_storage``).
    rag_root: Path | None = None

    @classmethod
    def default(cls) -> "Paths":
        # jenui/config/paths.py -> raíz del proyecto
        return cls(root=Path(__file__).resolve().parents[2])

    def with_rag_dir(self, rag_dir: str | Path | None) -> "Paths":
        """Copia que apunta a otro almacén de LightRAG.

        Permite tener un segundo grafo (p. ej. el del análisis temporal, en
        ``rag_storage_meta``) sin tocar el que usa el buscador. Las rutas
        relativas se resuelven desde la raíz del proyecto.
        """
        if not rag_dir:
            return self
        rag_dir = Path(rag_dir)
        if not rag_dir.is_absolute():
            rag_dir = self.root / rag_dir
        return replace(self, rag_root=rag_dir)

    # --- entradas ---
    @property
    def pdf_dir(self) -> Path:
        return self.root / "pdf"

    @property
    def fichas_dir(self) -> Path:
        return self.root / "fichas"

    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    # --- datos generados ---
    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def corpus_file(self) -> Path:
        return self.data_dir / "corpus.jsonl"

    @property
    def vectors_file(self) -> Path:
        return self.data_dir / "fulltext_vectors.npy"

    @property
    def vectors_meta_file(self) -> Path:
        return self.data_dir / "fulltext_meta.json"

    @property
    def manifest_file(self) -> Path:
        return self.data_dir / "index_manifest.json"

    @property
    def aliases_file(self) -> Path:
        """Mapa de alias semánticos. Es propio de cada grafo: el de un almacén
        alternativo vive dentro de él, para no pisar el del buscador."""
        if self.rag_root:
            return self.rag_root / "entity_aliases.json"
        return self.data_dir / "entity_aliases.json"

    @property
    def analysis_dir(self) -> Path:
        return self.data_dir / "analysis"

    @property
    def references_file(self) -> Path:
        return self.root / "fuentes" / "referencias_jenui.csv"

    # --- almacén de LightRAG ---
    @property
    def rag_dir(self) -> Path:
        return self.rag_root or self.root / "rag_storage"

    @property
    def graphml_file(self) -> Path:
        return self.rag_dir / "graph_chunk_entity_relation.graphml"

    @property
    def chunks_kv_file(self) -> Path:
        return self.rag_dir / "kv_store_text_chunks.json"

    # --- web ---
    @property
    def static_dir(self) -> Path:
        return self.root / "static"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.rag_dir):
            d.mkdir(parents=True, exist_ok=True)
