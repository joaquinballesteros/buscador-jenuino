"""Grafo de conocimiento cargado en memoria."""
from __future__ import annotations

import numpy as np

from jenui.config.settings import Settings
from jenui.graph.alias_resolver import AliasResolver
from jenui.graph.concept_index import ConceptIndex
from jenui.graph.entity_type_filter import EntityTypeFilter
from jenui.graph.graph_reader import GraphReader


class KnowledgeGraph:
    """Vista consultable del grafo: qué conceptos tiene cada artículo y al revés.

    Encapsula el trayecto completo desde los ficheros de LightRAG:
    leer → filtrar metadatos → consolidar variantes.

    Se recarga sola cuando el GraphML cambia, de modo que el buscador va
    incorporando el grafo mientras este se construye, sin reiniciar el servidor.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._filter = EntityTypeFilter(
            settings.search.get("tipos_entidad_descartados")
        )
        self._reader = GraphReader(
            settings.paths.graphml_file,
            settings.paths.chunks_kv_file,
            self._filter,
        )
        self._resolver = AliasResolver(settings.paths.aliases_file)
        self._concepts = ConceptIndex(settings.paths)

        self.entity_to_articles: dict[str, set[str]] = {}
        self.article_to_entities: dict[str, set[str]] = {}
        self.discarded = 0
        self.merged = 0
        self._mtime = 0.0
        self.load()

    # -------------------------------------------------------------------- estado
    @property
    def is_ready(self) -> bool:
        return bool(self.entity_to_articles)

    @property
    def n_entities(self) -> int:
        return len(self.entity_to_articles)

    @property
    def concept_source(self) -> str:
        """Origen del índice de conceptos: 'descripción', 'solo-nombre' o 'none'."""
        return self._concepts.source

    # --------------------------------------------------------------------- carga
    def load(self) -> None:
        if not self._reader.exists():
            return
        self._mtime = self._reader.mtime()
        try:
            raw = self._reader.read()
            self._resolver.reload()
            consolidated = self._resolver.consolidate(raw.entity_to_articles)
        except Exception as exc:  # noqa: BLE001 - un grafo a medio escribir no debe tumbar la búsqueda
            print(f"Aviso: no se pudo cargar el grafo: {exc}")
            return
        self.entity_to_articles = consolidated.entity_to_articles
        self.article_to_entities = consolidated.article_to_entities
        self.discarded = raw.discarded
        self.merged = consolidated.merged

    def reload(self) -> None:
        self.entity_to_articles = {}
        self.article_to_entities = {}
        self.discarded = self.merged = 0
        self._concepts = ConceptIndex(self._settings.paths)   # relee vectores nuevos
        self.load()

    def reload_if_changed(self) -> bool:
        """Recarga si el GraphML cambió. Devuelve si hubo recarga."""
        if self._reader.exists() and self._reader.mtime() != self._mtime:
            self.reload()
            return True
        return False

    # ------------------------------------------------------------------ consulta
    def entities_of(self, article_id: str) -> set[str]:
        return self.article_to_entities.get(article_id, set())

    def rank_concepts(self, concepts: set[str], limit: int = 8) -> list[str]:
        """Ordena conceptos del más específico al más genérico.

        Un concepto que solo comparten dos artículos explica su relación mucho
        mejor que otro presente en veinte, así que se prioriza por rareza. Sin
        esto, el orden alfabético dejaría arriba conceptos poco informativos.
        """
        return sorted(
            concepts, key=lambda c: (len(self.articles_of(c)), c)
        )[:limit]

    def articles_of(self, entity: str) -> set[str]:
        return self.entity_to_articles.get(entity, set())

    def related_articles(self, seed_ids: list[str], max_articles_per_entity: int,
                         query_vector: "np.ndarray | None" = None,
                         relevance_threshold: float | None = None,
                         relevance_factor: float = 0.5,
                         max_concepts: int | None = None
                         ) -> tuple[dict[str, float], dict[str, set[str]]]:
        """Artículos conectados a las semillas por conceptos compartidos.

        Devuelve ``(peso, conceptos)`` por artículo. Incluye a las propias
        semillas: reciben peso por los conceptos afines que ellas mismas
        aportan, igual que cualquier otro artículo (ver :meth:`_expand`). Se
        excluyen:

        * las entidades presentes en más de ``max_articles_per_entity``
          artículos, por demasiado genéricas para informar de nada;
        * si se pasa ``query_vector``, las entidades poco afines a la consulta.

        Este último filtro evita que un artículo-semilla genérico arrastre sus
        conceptos ajenos al tema buscado: para "retroalimentación formativa" no
        se expande por "Andragogía" solo porque una semilla la mencione.
        """
        seed_entities = self._seed_entities(seed_ids)
        relevance, _, kept = self._relevance_report(
            seed_entities, query_vector, relevance_threshold, relevance_factor,
            max_concepts,
        )
        return self._expand(kept, relevance, max_articles_per_entity)

    def explain_related(self, seed_ids: list[str], max_articles_per_entity: int,
                        query_vector, relevance_threshold: float | None,
                        relevance_factor: float, max_concepts: int | None = None) -> dict:
        """Como ``related_articles`` pero devolviendo también los pasos
        intermedios (para la página de testing): entidades semilla con su
        relevancia, el corte aplicado y qué se conservó."""
        seed_entities = self._seed_entities(seed_ids)
        scores, cutoff, kept = self._relevance_report(
            seed_entities, query_vector, relevance_threshold, relevance_factor,
            max_concepts,
        )
        weights, concepts = self._expand(kept, scores, max_articles_per_entity)
        return {
            "seed_entities": scores,          # {entidad: relevancia}  (None si sin vector)
            "cutoff": cutoff,
            "kept": kept,
            "weights": weights,
            "concepts": concepts,
        }

    def _seed_entities(self, seed_ids: list[str]) -> set[str]:
        entities: set[str] = set()
        for article_id in seed_ids:
            entities |= self.entities_of(article_id)
        return entities

    def _expand(self, entities: set[str], relevance: dict[str, float | None],
                max_per_entity: int) -> tuple[dict[str, float], dict[str, set[str]]]:
        """Suma, por artículo, la relevancia de las entidades que posee.

        Antes se sumaba ``+1`` por entidad compartida, sin distinguir un
        concepto muy afín a la consulta de uno marginal: con pocos conceptos
        por artículo (lo normal en este corpus) eso empataba casi todo en el
        mismo peso máximo tras normalizar. Pesar por relevancia da un empuje
        continuo en vez de casi binario.

        Incluye a las semillas: como sus propias entidades entran en
        ``entities``, acumulan peso por los conceptos afines que ellas aportan,
        igual que cualquier otro artículo — antes quedaban siempre a 0 por
        exclusión expresa, penalizando estructuralmente al artículo que suele
        ser el más central del tema (ver ``related_articles``).

        Sin índice de conceptos (``relevance`` a ``None``), cae a contar
        entidades compartidas (``+1``), el comportamiento previo.
        """
        weights: dict[str, float] = {}
        concepts: dict[str, set[str]] = {}
        for entity in entities:
            articles = self.articles_of(entity)
            if len(articles) > max_per_entity:
                continue
            weight = relevance.get(entity)
            weight = 1.0 if weight is None else weight
            for article_id in articles:
                weights[article_id] = weights.get(article_id, 0.0) + weight
                concepts.setdefault(article_id, set()).add(entity)
        return weights, concepts

    def _relevance_report(self, entities: set[str], query_vector,
                          threshold: float | None, factor: float,
                          max_concepts: int | None = None
                          ) -> tuple[dict[str, float | None], float | None, set[str]]:
        """Filtro de relevancia (opción B). Devuelve ``(scores, corte, conservadas)``.

        Tres criterios encadenados sobre la afinidad concepto-consulta:

        * un **suelo absoluto** (``threshold``), red de seguridad;
        * un **corte relativo por consulta** (``media + factor·desviación``);
        * un **tope al nº de conceptos** (``max_concepts``): se queda con los más
          afines. Es lo que evita que una consulta débil (p. ej. un acrónimo como
          "ABP", con señal floja) arrastre decenas de conceptos mediocres solo
          porque el corte relativo queda bajo.

        Las entidades sin vector se conservan (no se pueden juzgar). Requiere el
        índice de conceptos; si no está, no filtra.
        """
        scores: dict[str, float | None] = {e: None for e in entities}
        if query_vector is None or not self._concepts.is_available:
            return scores, None, set(entities)
        rated = self._concepts.relevances(entities, query_vector)
        scores.update(rated)
        if not rated:
            return scores, None, set(entities)
        values = np.fromiter(rated.values(), dtype=float)
        cutoff = values.mean() + factor * values.std()
        if threshold is not None:
            cutoff = max(cutoff, threshold)
        aprobados = sorted(((s, e) for e, s in rated.items() if s >= cutoff),
                           reverse=True)
        if max_concepts is not None:
            aprobados = aprobados[:max_concepts]
        kept = ({e for e in entities if e not in rated}
                | {e for _, e in aprobados})
        return scores, float(cutoff), kept
