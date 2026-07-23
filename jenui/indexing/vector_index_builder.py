"""Construcción incremental del índice vectorial."""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from jenui.config.settings import Settings
from jenui.domain.article import Article
from jenui.indexing.index_manifest import IndexManifest
from jenui.indexing.text_chunker import TextChunker
from jenui.indexing.vector_index import VectorIndex
from jenui.providers.provider_factory import ProviderFactory


@dataclass
class IndexReport:
    """Resultado de una construcción del índice vectorial."""

    total_articles: int
    already_indexed: int
    new_articles: int
    new_chunks: int
    total_chunks: int
    seconds: float


class VectorIndexBuilder:
    """Construye el índice vectorial de texto completo.

    Solo usa el modelo de embeddings, nunca el LLM, así que es rápido y sin
    coste de API aunque el grafo se construya por servicio externo.

    Es **incremental**: embebe únicamente los artículos que aún no están en el
    índice y los añade a los existentes.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._paths = settings.paths
        self._embeddings = ProviderFactory(settings).embeddings()
        self._manifest = IndexManifest(settings.paths.manifest_file)
        self._chunker = TextChunker(
            chunk_chars=settings.fulltext.get("chunk_chars", 1200),
            overlap_chars=settings.fulltext.get("overlap_chars", 150),
        )
        self._batch_size = settings.fulltext.get("batch_size", 16)

    @property
    def embeddings(self):
        return self._embeddings

    def build(self, articles: list[Article], rebuild: bool = False,
              verbose: bool = True) -> IndexReport:
        index = VectorIndex()
        if not rebuild:
            self._manifest.check_embeddings(self._embeddings)
            index = VectorIndex.load(
                self._paths.vectors_file, self._paths.vectors_meta_file
            )
            self._guard_dimension(index)

        indexed = index.indexed_article_ids()
        pending = [a for a in articles if a.id not in indexed]
        if verbose:
            print(f"Embeddings: {self._embeddings.name}/{self._embeddings.model} "
                  f"(dim {self._embeddings.dim})")
            print(f"Artículos: {len(articles)}  |  ya indexados: {len(indexed)}  "
                  f"|  nuevos: {len(pending)}")

        started = time.time()
        if not pending:
            return IndexReport(len(articles), len(indexed), 0, 0, index.n_chunks, 0.0)

        meta, texts = self._prepare(pending)
        if verbose:
            print(f"{len(pending)} artículos -> {len(texts)} fragmentos nuevos...")
        vectors = self._embed_all(texts, verbose=verbose)

        index.extend(vectors, meta)
        index.save(self._paths.vectors_file, self._paths.vectors_meta_file)
        self._manifest.save(embeddings=self._embeddings)

        return IndexReport(
            total_articles=len(articles),
            already_indexed=len(indexed),
            new_articles=len(pending),
            new_chunks=len(texts),
            total_chunks=index.n_chunks,
            seconds=time.time() - started,
        )

    # ------------------------------------------------------------------ interno
    def _prepare(self, articles: list[Article]) -> tuple[list[dict], list[str]]:
        meta: list[dict] = []
        texts: list[str] = []
        for article in articles:
            for position, (display, embed) in enumerate(self._chunker.split_article(article)):
                meta.append({
                    "article_id": article.id,
                    "chunk_index": position,
                    "text": display[:400],     # solo para mostrar contexto
                })
                texts.append(embed)
        return meta, texts

    def _embed_all(self, texts: list[str], verbose: bool) -> np.ndarray:
        vectors = np.zeros((len(texts), self._embeddings.dim), dtype=np.float32)
        started = time.time()
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start:start + self._batch_size]
            vectors[start:start + len(batch)] = self._embeddings.embed(batch)
            if verbose and (start // self._batch_size) % 10 == 0:
                done = min(start + self._batch_size, len(texts))
                rate = done / max(time.time() - started, 1e-6)
                print(f"  {done}/{len(texts)}  ({rate:.1f} emb/s)")
        return VectorIndex.normalize(vectors)

    def _guard_dimension(self, index: VectorIndex) -> None:
        """La dimensión real manda sobre el manifiesto: si no coincide, aborta."""
        if index.dim is not None and index.dim != self._embeddings.dim:
            raise SystemExit(
                f"\n[ERROR] El índice existente tiene dim {index.dim} y el "
                f"embedding actual ({self._embeddings.name}/{self._embeddings.model}) "
                f"produce dim {self._embeddings.dim}.\n"
                f"Reconstruye con: python build_fulltext.py --rebuild\n"
            )
