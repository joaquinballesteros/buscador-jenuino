"""Construcción del grafo de conocimiento con LightRAG."""
from __future__ import annotations

import time
from dataclasses import dataclass

from jenui.config.settings import Settings
from jenui.domain.article import Article
from jenui.indexing.index_manifest import IndexManifest
from jenui.providers.provider_factory import ProviderFactory

#: Ontología por defecto si no se define en ``config.json``.
DEFAULT_ENTITY_TYPES = [
    "metodologia_docente",
    "herramienta",
    "tecnologia",
    "asignatura",
    "competencia",
    "instrumento_evaluacion",
    "concepto_educativo",
]


@dataclass
class GraphReport:
    """Resultado de una construcción del grafo."""

    articles: int
    scope: str
    seconds: float


class GraphBuilder:
    """Construye el grafo de entidades y relaciones sobre el corpus.

    **La ontología es el ajuste decisivo.** La ontología genérica que trae
    LightRAG (``Person``, ``Organization``, ``Location``…) hace que el extractor
    saque autores, departamentos y universidades: metadatos que no relacionan
    artículos por tema. Medido sobre este corpus, con la ontología por defecto
    el 49 % de las entidades eran metadatos y el 94 % aparecía en un solo
    artículo, es decir, no conectaba nada. La ontología de dominio de
    ``config.json`` (``graph.entity_types``) corrige justo eso.

    El ámbito (``scope``) decide qué se le da al extractor:

    * ``meta`` — título, palabras clave y resumen. Una llamada por artículo.
    * ``full`` — además, el cuerpo completo. Muchas más llamadas, pero capta lo
      específico (herramientas, asignaturas, instrumentos), que es lo que hace
      útiles los "artículos relacionados".

    LightRAG salta solo los documentos ya procesados, así que volver a lanzarlo
    tras añadir artículos procesa únicamente los nuevos.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._paths = settings.paths
        factory = ProviderFactory(settings)
        self._embeddings = factory.embeddings()
        self._llm = factory.llm()
        self._manifest = IndexManifest(settings.paths.manifest_file)
        self._config = settings.graph

    @property
    def entity_types(self) -> list[str]:
        return self._config.get("entity_types", DEFAULT_ENTITY_TYPES)

    @property
    def default_scope(self) -> str:
        return self._config.get("scope", "meta")

    def build_document(self, article: Article, scope: str) -> str:
        """Texto que se entrega al extractor para un artículo.

        La cabecera con metadatos ayuda al modelo a situar el contenido.
        """
        lines = [f"# {article.title or article.id}"]
        if article.authors:
            lines.append(f"Autores: {article.authors}")
        if article.year:
            lines.append(f"Año: {article.year} (JENUI)")
        if article.keywords:
            lines.append(f"Palabras clave: {article.keywords}")
        if article.abstract:
            lines.append(f"Resumen: {article.abstract}")
        document = "\n".join(lines)
        if scope == "full":
            document += "\n\n" + article.text
        return document

    async def create_rag(self):
        """Instancia LightRAG con los proveedores y la ontología configurados."""
        from lightrag import LightRAG
        from lightrag.kg.shared_storage import initialize_pipeline_status

        self._manifest.check_embeddings(self._embeddings)
        warning = self._manifest.warn_if_llm_changed(self._llm)
        if warning:
            print(warning)

        rag = LightRAG(
            working_dir=str(self._paths.rag_dir),
            embedding_func=self._embeddings.as_lightrag_func(),
            chunk_token_size=self._config.get("chunk_token_size", 1800),
            chunk_overlap_token_size=self._config.get("chunk_overlap_token_size", 100),
            addon_params={
                "language": self._config.get("language", "Spanish"),
                "entity_types": self.entity_types,
            },
            entity_extract_max_gleaning=self._config.get(
                "entity_extract_max_gleaning", 1
            ),
            **self._llm.as_lightrag_kwargs(),
        )
        await rag.initialize_storages()
        await initialize_pipeline_status()
        self._manifest.save(embeddings=self._embeddings, llm=self._llm)
        return rag

    async def build(self, articles: list[Article], scope: str | None = None,
                    verbose: bool = True) -> GraphReport:
        scope = scope or self.default_scope
        if verbose:
            print(f"Artículos en corpus: {len(articles)}  |  ámbito: {scope}")
            print(f"LLM: {self._llm.name}/{self._llm.model}  |  "
                  f"Embeddings: {self._embeddings.name}/{self._embeddings.model}")
            print(f"Almacén: {self._paths.rag_dir}")
            print("(LightRAG salta los documentos ya procesados)\n")

        rag = await self.create_rag()
        started = time.time()
        await rag.ainsert(
            [self.build_document(a, scope) for a in articles],
            ids=[a.id for a in articles],
            file_paths=[a.filename for a in articles],
        )
        elapsed = time.time() - started
        await rag.finalize_storages()
        return GraphReport(articles=len(articles), scope=scope, seconds=elapsed)
