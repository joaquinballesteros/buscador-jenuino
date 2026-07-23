"""Motor de búsqueda."""
from __future__ import annotations

from jenui.config.settings import Settings
from jenui.domain.search_result import SearchResult
from jenui.graph.knowledge_graph import KnowledgeGraph
from jenui.indexing.vector_index import VectorIndex
from jenui.ingestion.corpus_repository import CorpusRepository
from jenui.providers.provider_factory import ProviderFactory
from jenui.search.ranker import Ranker
from jenui.search.spell_corrector import SpellCorrector


class Searcher:
    """Busca artículos relacionados con una consulta.

    Combina dos recuperadores complementarios:

    1. **Vectorial sobre texto completo** — cubre el cuerpo entero del artículo
       y ordena por parecido con la consulta.
    2. **Grafo de conocimiento** — parte de los mejores resultados y añade los
       artículos que comparten conceptos con ellos, aunque su texto no case.

    Están separados a propósito: el vectorial es barato de construir y de
    actualizar, mientras que el grafo cuesta horas de extracción. Así un
    artículo nuevo es buscable en segundos y el grafo lo enriquece después.

    **Ninguna búsqueda invoca al LLM**: solo se embebe la consulta y se hace un
    producto matricial, de modo que responde en milisegundos y sin coste.

    El corpus, el índice y el grafo se recargan solos cuando cambian sus
    ficheros, así que añadir artículos no obliga a reiniciar el servidor.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._paths = settings.paths
        self.embeddings = ProviderFactory(settings).embeddings()
        self._repository = CorpusRepository(settings.paths.corpus_file)

        self.articles = {}
        self.index = VectorIndex()
        self._data_mtime = (0.0, 0.0)
        self._load_data()

        self.graph = KnowledgeGraph(settings)

    # --------------------------------------------------------------------- carga
    def _load_data(self) -> None:
        self.articles = self._repository.load_by_id()
        self.index = VectorIndex.load(
            self._paths.vectors_file, self._paths.vectors_meta_file
        )
        self._corrector = SpellCorrector.from_articles(self.articles.values())
        self._data_mtime = self._current_data_mtime()

    def _current_data_mtime(self) -> tuple[float, float]:
        vectors = (self._paths.vectors_file.stat().st_mtime
                   if self._paths.vectors_file.exists() else 0.0)
        return (self._repository.mtime(), vectors)

    def refresh(self) -> None:
        """Recarga todo: corpus, índice y grafo."""
        self._load_data()
        self.graph.reload()

    def refresh_if_changed(self) -> None:
        """Recarga solo lo que haya cambiado en disco."""
        if self._current_data_mtime() != self._data_mtime:
            self._load_data()
        self.graph.reload_if_changed()

    # ------------------------------------------------------------------- estado
    def status(self) -> dict:
        self.refresh_if_changed()
        return {
            "articulos": len(self.articles),
            "chunks": self.index.n_chunks,
            "fulltext_listo": self.index.is_ready,
            "grafo_listo": self.graph.is_ready,
            "entidades": self.graph.n_entities,
            "entidades_descartadas": self.graph.discarded,
            "entidades_fusionadas": self.graph.merged,
            "embeddings": f"{self.embeddings.name}/{self.embeddings.model}",
        }

    # ----------------------------------------------------------------- búsqueda
    def search(self, query: str, top_k: int | None = None,
               spellcheck: bool | None = None) -> dict:
        self.refresh_if_changed()
        config = self._settings.search
        top_k = top_k or config.get("top_k", 15)
        do_correct = (config.get("corregir_ortografia", True)
                      if spellcheck is None else spellcheck)

        if not self.index.is_ready:
            return {
                "error": "El índice full-text no existe. Ejecuta build_fulltext.py.",
                "results": [],
            }

        correction = self._corrector.correct(query)
        if do_correct and correction.changed:
            query = correction.corrected

        query_vector = self.embeddings.embed_one(query)
        text_hits = self.index.score_articles(
            query_vector,
            pooling=config.get("pooling", "hybrid"),
            k=config.get("pooling_k", 3),
            alpha=config.get("pooling_alpha", 0.5),
        )

        seed_ids = self._pick_seeds(text_hits, config)
        graph_weights: dict[str, float] = {}
        shared_concepts: dict[str, set[str]] = {}
        if self.graph.is_ready and seed_ids:
            graph_weights, shared_concepts = self.graph.related_articles(
                seed_ids,
                config.get("max_articulos_por_entidad", 12),
                query_vector=query_vector,
                relevance_threshold=config.get("umbral_concepto", 0.10),
                relevance_factor=config.get("factor_relativo", 0.5),
                max_concepts=config.get("max_conceptos_semilla", 20),
            )

        ranker = Ranker(
            text_weight=config.get("peso_texto", 0.85),
            graph_weight=config.get("peso_grafo", 0.15),
        )
        ranked = ranker.rank(text_hits, graph_weights, top_k)

        results = [
            self._to_result(article_id, score, text_hits, shared_concepts)
            for article_id, score in ranked
            if article_id in self.articles
        ]
        applied = do_correct and correction.changed
        return {
            "query": query,
            "corregido": correction.corrected if applied else None,
            "original": correction.original if applied else None,
            "graph_ready": self.graph.is_ready,
            "results": [r.to_dict() for r in results],
        }

    def explain(self, query: str, top_k: int | None = None,
                limit_text: int = 25) -> dict:
        """Versión instrumentada de :meth:`search` para la página de testing.

        Devuelve cada etapa por separado —corrección, recuperador vectorial,
        grafo de conocimiento y ranker— reutilizando exactamente los mismos
        componentes que la búsqueda real, para que refleje lo que de verdad pasa.
        """
        self.refresh_if_changed()
        config = self._settings.search
        top_k = top_k or config.get("top_k", 15)
        if not self.index.is_ready:
            return {"error": "El índice full-text no existe."}

        pooling = {"mode": config.get("pooling", "hybrid"),
                   "k": config.get("pooling_k", 3),
                   "alpha": config.get("pooling_alpha", 0.5)}

        # --- corrección ortográfica ---
        correction = self._corrector.correct(query)
        applied = config.get("corregir_ortografia", True) and correction.changed
        used_query = correction.corrected if applied else query

        # --- etapa 1: recuperador vectorial (con detalle de fragmentos) ---
        query_vector = self.embeddings.embed_one(used_query)
        detail = self.index.article_scores_detail(
            query_vector, pooling["mode"], pooling["k"], pooling["alpha"]
        )
        text_hits = self.index.score_articles(
            query_vector, pooling["mode"], pooling["k"], pooling["alpha"]
        )
        text_stage = [self._label(d) for d in detail[:limit_text]]

        # --- etapa 2: grafo de conocimiento ---
        seed_ids = self._pick_seeds(text_hits, config)
        graph_stage = {
            "ready": self.graph.is_ready,
            "concept_index": self.graph.concept_source,
            "seeds": [self._brief(a) for a in seed_ids],
            "seed_entities": [], "cutoff": None, "related": [],
        }
        graph_weights: dict[str, float] = {}
        shared_concepts: dict[str, set[str]] = {}
        if self.graph.is_ready and seed_ids:
            info = self.graph.explain_related(
                seed_ids, config.get("max_articulos_por_entidad", 12),
                query_vector, config.get("umbral_concepto", 0.10),
                config.get("factor_relativo", 0.5),
                max_concepts=config.get("max_conceptos_semilla", 20),
            )
            graph_weights, shared_concepts = info["weights"], info["concepts"]
            graph_stage["cutoff"] = info["cutoff"]
            entities = sorted(
                ({"entity": e, "relevance": (round(s, 4) if s is not None else None),
                  "kept": e in info["kept"]}
                 for e, s in info["seed_entities"].items()),
                # primero las usadas, luego por relevancia descendente
                key=lambda x: (not x["kept"], x["relevance"] is None, -(x["relevance"] or 0)),
            )
            graph_stage["seed_entities_total"] = len(entities)
            graph_stage["seed_entities_kept"] = sum(1 for x in entities if x["kept"])
            graph_stage["seed_entities"] = entities[:limit_text * 3]
            graph_stage["related"] = sorted(
                ({**self._brief(a), "peso": round(graph_weights[a], 4),
                  "conceptos": sorted(shared_concepts.get(a, set()))[:8]}
                 for a in graph_weights),
                key=lambda x: -x["peso"],
            )[:limit_text]

        # --- etapa 3: ranker ---
        w_texto = config.get("peso_texto", 0.85)
        w_grafo = config.get("peso_grafo", 0.15)
        max_boost = max(graph_weights.values()) if graph_weights else 1.0
        ranker = Ranker(text_weight=w_texto, graph_weight=w_grafo)
        ranked = ranker.rank(text_hits, graph_weights, top_k)
        rank_stage = []
        for pos, (aid, final) in enumerate(ranked, 1):
            if aid not in self.articles:
                continue
            ts = text_hits[aid].score if aid in text_hits else 0.0
            gnorm = graph_weights.get(aid, 0.0) / max_boost
            rank_stage.append({**self._brief(aid), "rank": pos,
                               "text_score": round(ts, 4),
                               "graph_raw": round(graph_weights.get(aid, 0.0), 4),
                               "graph_norm": round(gnorm, 4),
                               "final": round(final, 4)})

        return {
            "query": query,
            "correction": {"original": correction.original,
                           "corrected": correction.corrected, "applied": applied},
            "used_query": used_query,
            "pooling": pooling,
            "weights": {"texto": w_texto, "grafo": w_grafo},
            "text_retriever": text_stage,
            "graph": graph_stage,
            "ranker": rank_stage,
        }

    def _brief(self, article_id: str) -> dict:
        a = self.articles.get(article_id)
        return {"id": article_id,
                "title": (a.title if a else article_id) or article_id,
                "year": a.year if a else None}

    def _label(self, detail: dict) -> dict:
        return {**detail, **self._brief(detail["article_id"])}

    def _pick_seeds(self, text_hits: dict, config: dict) -> list[str]:
        """Artículos que siembran la expansión por grafo (opción A).

        Se toman pocos y solo si se parecen de verdad a la consulta: un artículo
        genérico que entra al fondo del ranking arrastraría sus conceptos ajenos
        al tema. Se conserva al menos el mejor, para no perder el grafo del todo.
        """
        ranked = sorted(text_hits.items(), key=lambda item: item[1].score,
                        reverse=True)
        n_seeds = config.get("n_semillas", 3)
        floor = config.get("umbral_semilla", 0.5)
        seeds = [aid for aid, hit in ranked[:n_seeds] if hit.score >= floor]
        if not seeds and ranked:
            seeds = [ranked[0][0]]
        return seeds

    def _to_result(self, article_id: str, score: float, text_hits: dict,
                   shared_concepts: dict) -> SearchResult:
        hit = text_hits.get(article_id)
        return SearchResult(
            article=self.articles[article_id],
            score=score,
            text_score=hit.score if hit else 0.0,
            # los más específicos primero: explican mejor la relación
            shared_concepts=self.graph.rank_concepts(
                shared_concepts.get(article_id, set())
            ),
        )
