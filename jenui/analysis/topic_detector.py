"""Agrupación de conceptos en topics."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable

import networkx as nx

from jenui.analysis.concept_source import ConceptCorpus


@dataclass
class Topic:
    """Un tema: un grupo de conceptos que suelen aparecer juntos."""

    id: str
    concepts: list[str]            # claves, de más a menos central
    label: str
    articles: set[str] = field(default_factory=set)


class TopicDetector:
    """Detecta topics como comunidades del grafo de coocurrencia de conceptos.

    Las entidades del grafo son demasiado finas para seguirlas en el tiempo:
    "ChatGPT", "IA generativa" y "GitHub Copilot" son un mismo tema. Se agrupan
    por **coocurrencia** (aparecen en los mismos artículos), el criterio
    clásico del análisis de co-palabras, en vez de por parecido del nombre:
    así se juntan también conceptos que no se parecen pero van de la mano.

    * Arista entre dos conceptos si coinciden en ``min_cooc`` artículos o más,
      con peso de Salton ``c_ij / sqrt(df_i · df_j)``. El recuento en bruto
      haría que los conceptos más frecuentes atrajeran a todos los demás.
    * Comunidades con Louvain (``networkx``), con semilla fija para que dos
      ejecuciones den los mismos topics.
    * Un artículo pertenece a un topic si tiene al menos ``min_shared`` de sus
      conceptos. Con uno solo bastaría una mención de pasada para contar.
    * Los *hubs* del corpus (ver :class:`ConceptCorpus`) quedan fuera.
    """

    def __init__(self, min_df: int = 4, min_cooc: int = 2, resolution: float = 1.0,
                 seed: int = 42, min_size: int = 3, min_shared: int = 2) -> None:
        self.min_df = min_df
        self.min_cooc = min_cooc
        self.resolution = resolution
        self.seed = seed
        self.min_size = min_size
        self.min_shared = min_shared

    @classmethod
    def from_params(cls, params: dict, **overrides) -> "TopicDetector":
        values = dict(
            min_df=params.get("min_articulos_concepto", 4),
            min_cooc=params.get("min_coocurrencias", 2),
            resolution=params.get("resolucion", 1.0),
            seed=params.get("semilla", 42),
            min_size=params.get("min_conceptos_topic", 3),
            min_shared=params.get("min_conceptos_articulo", 2),
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    def detect(self, corpus: ConceptCorpus, article_ids: Iterable[str] | None = None,
               prefix: str = "T") -> list[Topic]:
        """Topics de ``article_ids`` (por defecto, todo el corpus)."""
        ids = set(corpus.article_concepts if article_ids is None else article_ids)
        hubs = corpus.hub_keys
        concepts = {a: corpus.article_concepts[a] - hubs for a in ids
                    if a in corpus.article_concepts}
        graph = self.cooccurrence_graph(concepts)
        if graph.number_of_edges() == 0:
            return []

        communities = nx.community.louvain_communities(
            graph, weight="weight", resolution=self.resolution, seed=self.seed
        )
        topics = []
        for community in communities:
            if len(community) < self.min_size:
                continue
            strength = dict(graph.subgraph(community).degree(weight="weight"))
            ordered = sorted(community, key=lambda c: (-strength[c], c))
            members = {a for a, cs in concepts.items()
                       if len(cs & community) >= self.min_shared}
            if not members:
                continue
            label = " · ".join(corpus.label(c) for c in ordered[:3])
            topics.append(Topic("", ordered, label, members))

        topics.sort(key=lambda t: (-len(t.articles), t.label))
        width = len(str(len(topics)))
        for number, topic in enumerate(topics, start=1):
            topic.id = f"{prefix}{number:0{max(width, 2)}d}"
        return topics

    def cooccurrence_graph(self, concepts: dict[str, set[str]]) -> nx.Graph:
        df = Counter(c for cs in concepts.values() for c in cs)
        vocabulary = {c for c, n in df.items() if n >= self.min_df}
        pairs: Counter = Counter()
        for article_concepts in concepts.values():
            pairs.update(combinations(sorted(article_concepts & vocabulary), 2))

        graph = nx.Graph()
        for (a, b), count in pairs.items():
            if count >= self.min_cooc:
                graph.add_edge(a, b, weight=count / math.sqrt(df[a] * df[b]),
                               count=count)
        return graph
