"""Orquestación del análisis temporal de topics."""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass

from jenui.analysis.citation_links import CitationNetwork
from jenui.analysis.concept_source import ConceptCorpus, ConceptCorpusBuilder
from jenui.analysis.topic_detector import Topic, TopicDetector
from jenui.analysis.topic_evolution import CLASSES, TopicEvolution
from jenui.analysis.topic_flow import TopicFlowBuilder
from jenui.config.settings import Settings
from jenui.ingestion.corpus_repository import CorpusRepository


@dataclass
class AnalysisOptions:
    """Ajustes de una ejecución que la línea de órdenes puede sobrescribir."""

    source: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    resolution: float | None = None
    min_df: int | None = None


class TopicAnalysis:
    """Corpus → conceptos → topics → series y clases → flujo y citas.

    Devuelve un diccionario serializable (``run``) que consume
    :class:`~jenui.analysis.report_writer.ReportWriter`. No llama al LLM: todo
    sale del grafo ya construido y de los metadatos del corpus.
    """

    def __init__(self, settings: Settings, options: AnalysisOptions | None = None) -> None:
        self._settings = settings
        self._options = options or AnalysisOptions()
        self._params = settings.section("analysis")

    def run(self, verbose: bool = True) -> dict:
        started = time.time()
        log = print if verbose else (lambda *_: None)
        options = self._options

        articles = CorpusRepository(self._settings.paths.corpus_file).load_all()
        if not articles:
            raise SystemExit("El corpus está vacío. Ejecuta scripts/ingest.py primero.")
        builder = ConceptCorpusBuilder(self._settings, options.source)
        log(f"Fuente de conceptos: {builder.source}  |  "
            f"grafo: {self._settings.paths.rag_dir.name}")
        corpus = builder.build(articles, options.year_from, options.year_to)
        if not corpus.article_year:
            raise SystemExit("Ningún artículo tiene conceptos en el rango pedido.")
        if corpus.mentions_discarded:
            log(f"Menciones de pasada descartadas (fuera del núcleo): "
                f"{corpus.mentions_discarded}")
        log(f"Artículos con conceptos: {len(corpus.article_year)}  |  "
            f"años: {corpus.years[0]}–{corpus.years[-1]}  |  "
            f"conceptos: {len(corpus.concept_articles())}")

        detector = TopicDetector.from_params(
            self._params, resolution=options.resolution, min_df=options.min_df
        )
        topics = detector.detect(corpus)
        log(f"Topics detectados: {len(topics)}")

        evolution = TopicEvolution(corpus, self._params.get("ventana_suavizado", 3),
                                   self._params.get("clasificacion"))
        citations = CitationNetwork.load(self._settings.paths.references_file)

        flow_params = self._params.get("flujo", {})
        flow_detector = TopicDetector.from_params(
            self._params, resolution=options.resolution,
            min_df=flow_params.get("min_articulos_concepto", 3),
        )
        flow = TopicFlowBuilder(
            flow_detector,
            window=flow_params.get("ventana", 5),
            jaccard_threshold=flow_params.get("umbral_jaccard", 0.1),
            min_articles=flow_params.get("min_articulos_comunidad", 5),
        ).build(corpus, topics)
        log(f"Flujo: {len(flow.windows)} ventanas, {len(flow.nodes)} topics por ventana, "
            f"{len(flow.links)} enlaces")

        topic_rows = [self._topic_row(t, corpus, evolution, citations) for t in topics]
        emerging = evolution.emerging_concepts(detector.min_df)
        totals = corpus.year_totals()

        return {
            "meta": {
                "generado": time.strftime("%Y-%m-%d %H:%M"),
                "segundos": round(time.time() - started, 1),
                "fuente": corpus.source,
                "grafo_dir": self._settings.paths.rag_dir.name,
                "anios": corpus.years,
                "articulos_por_anio": [totals[y] for y in corpus.years],
                "n_articulos": len(corpus.article_year),
                "n_conceptos": len(corpus.concept_articles()),
                "ruido_descartado": corpus.noise_discarded,
                "menciones_descartadas": corpus.mentions_discarded,
                "hubs": [{"concepto": corpus.label(c), "articulos": n}
                         for c, n in corpus.hubs],
                "clases": CLASSES,
                "parametros": {
                    "min_articulos_concepto": detector.min_df,
                    "min_coocurrencias": detector.min_cooc,
                    "resolucion": detector.resolution,
                    "relevancia_grafo": self._params.get("relevancia_grafo", "nucleo"),
                    "min_fragmentos": self._params.get("min_fragmentos", 2),
                    "min_conceptos_articulo": detector.min_shared,
                    "ventana_suavizado": self._params.get("ventana_suavizado", 3),
                    "clasificacion": evolution.params,
                    "flujo": flow_params,
                },
                "citas": ({"citas_jenui": citations.n_edges,
                           "articulos_con_referencias": citations.n_citing}
                          if citations else None),
            },
            "topics": topic_rows,
            "emergentes": [
                {**asdict(e), "pioneros": [self._article(a, corpus) for a in e.pioneros[:3]]}
                for e in emerging
            ],
            "flujo": {
                "ventanas": flow.windows,
                "nodos": [{**asdict(n), "concepts": [corpus.label(c) for c in
                                                     sorted(n.concepts)][:12]}
                          for n in flow.nodes],
                "enlaces": [asdict(link) for link in flow.links],
            },
            "conceptos": self._concept_series(corpus, detector.min_df),
        }

    # ------------------------------------------------------------------ filas
    def _topic_row(self, topic: Topic, corpus: ConceptCorpus,
                   evolution: TopicEvolution, citations: CitationNetwork | None) -> dict:
        series = evolution.series(topic.articles)
        profile = evolution.classify(series)
        concepts = set(topic.concepts)
        centrality = {a: len(corpus.article_concepts[a] & concepts) for a in topic.articles}
        central = sorted(topic.articles, key=lambda a: (-centrality[a], a))[:8]

        row = {
            "id": topic.id,
            "label": topic.label,
            "conceptos": [corpus.label(c) for c in topic.concepts[:20]],
            "n_conceptos": len(topic.concepts),
            "n_articulos": len(topic.articles),
            **asdict(profile),
            "serie": asdict(series),
            "articulos_centrales": [self._article(a, corpus) for a in central],
            "pioneros": [],
            "citas": None,
        }
        if profile.anio_inicio is not None:
            limit = profile.anio_inicio + 2
            early = [a for a in topic.articles if corpus.article_year[a] <= limit]
            early.sort(key=lambda a: (corpus.article_year[a], -centrality[a], a))
            row["pioneros"] = [self._article(a, corpus) for a in early[:5]]
        if citations:
            stats = citations.topic_stats(topic.articles, corpus.article_year,
                                          profile.anio_inicio)
            row["citas"] = {
                **asdict(stats),
                "mas_citados": [{**self._article(a, corpus), "citas": n}
                                for a, n in stats.mas_citados],
                "fraccion_citan_pioneros": stats.fraccion_citan_pioneros,
            }
        return row

    @staticmethod
    def _article(article_id: str, corpus: ConceptCorpus) -> dict:
        return {"id": article_id,
                "anio": corpus.article_year.get(article_id),
                "titulo": corpus.article_title.get(article_id, "")}

    @staticmethod
    def _concept_series(corpus: ConceptCorpus, min_df: int) -> list[dict]:
        years = corpus.years
        rows = []
        for concept, articles in corpus.concept_articles().items():
            if len(articles) < min_df:
                continue
            per_year = Counter(corpus.article_year[a] for a in articles)
            rows.append({"concepto": corpus.label(concept), "articulos": len(articles),
                         "conteos": [per_year[y] for y in years]})
        rows.sort(key=lambda r: (-r["articulos"], r["concepto"]))
        return rows
