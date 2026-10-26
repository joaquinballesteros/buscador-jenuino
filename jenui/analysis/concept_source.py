"""Conceptos de cada artículo, la materia prima del análisis temporal."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from jenui.config.settings import Settings
from jenui.domain.article import Article
from jenui.graph.alias_resolver import AliasResolver
from jenui.graph.entity_type_filter import EntityTypeFilter
from jenui.graph.graph_reader import GraphReader

#: Orígenes de conceptos admitidos.
SOURCES = ("grafo", "keywords", "ambos")

#: Separadores de la lista de palabras clave de una ficha.
KEYWORD_SPLIT = re.compile(r"[;,·•]|\s[-–]\s")


class NoiseFilter:
    """Descarta los conceptos que no son temas.

    Complementa a :class:`~jenui.graph.entity_type_filter.EntityTypeFilter`,
    que filtra por *tipo*: aquí se filtra por *nombre*. Con ``scope full`` el
    extractor saca referencias a figuras y tablas ("Figura 2" aparece en 74
    artículos), cursos académicos y nombres de actas. Para un buscador es ruido
    tolerable; para una serie temporal no, porque un concepto con fecha
    ("Curso 2023/2024", "JENUI 2024") sale emergente por construcción.

    Se compara sobre el nombre ya normalizado por :class:`AliasResolver`.
    """

    def __init__(self, patterns: list[str], generic: list[str]) -> None:
        self._patterns = [re.compile(p) for p in patterns]
        self._generic = {AliasResolver.normalize(g) for g in generic}

    def is_noise(self, key: str) -> bool:
        if len(key) < 3 or not re.search(r"[a-z]", key):
            return True
        if key in self._generic:
            return True
        return any(p.search(key) for p in self._patterns)


@dataclass
class ConceptCorpus:
    """Artículos con año y conceptos ya limpios y consolidados.

    Los conceptos se identifican por su clave de fusión (ver
    :meth:`AliasResolver.group_key`); ``labels`` da el nombre a mostrar.
    """

    source: str
    article_year: dict[str, int]
    article_title: dict[str, str]
    article_concepts: dict[str, set[str]]
    labels: dict[str, str]
    noise_discarded: int = 0
    #: Conceptos demasiado frecuentes, con su nº de artículos. Siguen en el
    #: corpus (tienen su serie), pero no participan en la detección de topics.
    hubs: list[tuple[str, int]] = field(default_factory=list)

    @property
    def hub_keys(self) -> set[str]:
        return {concept for concept, _ in self.hubs}

    @property
    def years(self) -> list[int]:
        return sorted(set(self.article_year.values()))

    def year_totals(self) -> Counter:
        """Artículos por año (el denominador de la prevalencia)."""
        return Counter(self.article_year.values())

    def concept_articles(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = defaultdict(set)
        for article_id, concepts in self.article_concepts.items():
            for concept in concepts:
                result[concept].add(article_id)
        return dict(result)

    def label(self, concept: str) -> str:
        return self.labels.get(concept, concept)


class ConceptCorpusBuilder:
    """Reúne los conceptos de cada artículo desde el grafo y/o las palabras clave.

    Las dos fuentes se complementan:

    * **grafo** — conceptos extraídos por el LLM, homogéneos en todas las
      épocas porque el mismo modelo lee todos los artículos;
    * **keywords** — las palabras clave de los autores: limpias y sin coste,
      pero cada época las escribe a su manera y no todas las fichas las traen.

    Ambas comparten la clave de fusión, de modo que la palabra clave
    "Gamificación" y la entidad "GAMIFICACIÓN" son el mismo concepto.
    """

    def __init__(self, settings: Settings, source: str | None = None) -> None:
        self._settings = settings
        self._params = settings.section("analysis")
        self.source = source or self._params.get("fuente", "ambos")
        if self.source not in SOURCES:
            raise ValueError(f"fuente desconocida: {self.source!r} (usa {SOURCES})")
        aliases = (settings.paths.aliases_file
                   if self._params.get("usar_alias_semanticos", True) else None)
        self._resolver = AliasResolver(aliases)
        self._noise = NoiseFilter(self._params.get("patrones_ruido", []),
                                  self._params.get("conceptos_genericos", []))
        self._reader = GraphReader(
            settings.paths.graphml_file,
            settings.paths.chunks_kv_file,
            EntityTypeFilter(settings.search.get("tipos_entidad_descartados")),
        )

    def build(self, articles: list[Article], year_from: int | None = None,
              year_to: int | None = None) -> ConceptCorpus:
        articles = [
            a for a in articles
            if a.year
            and (year_from is None or a.year >= year_from)
            and (year_to is None or a.year <= year_to)
        ]
        allowed = {a.id for a in articles}
        concepts: dict[str, set[str]] = defaultdict(set)
        surfaces: dict[str, Counter] = defaultdict(Counter)
        noise = 0

        if self.source in ("grafo", "ambos"):
            noise += self._add_graph(allowed, concepts, surfaces)
        if self.source in ("keywords", "ambos"):
            noise += self._add_keywords(articles, concepts, surfaces)

        years = {a.id: a.year for a in articles if concepts.get(a.id)}
        concepts = self._drop_sparse_years(years, concepts)
        hubs = self._find_hubs(concepts)

        return ConceptCorpus(
            source=self.source,
            article_year={a: y for a, y in years.items() if a in concepts},
            article_title={a.id: a.title for a in articles if a.id in concepts},
            article_concepts=concepts,
            labels={key: self._pick_label(forms) for key, forms in surfaces.items()},
            noise_discarded=noise,
            hubs=hubs,
        )

    # ------------------------------------------------------------------ fuentes
    def _add_graph(self, allowed: set[str], concepts, surfaces) -> int:
        if not self._reader.exists():
            raise SystemExit(
                f"No hay grafo en {self._settings.paths.rag_dir}.\n"
                "Constrúyelo con: python scripts/build_graph.py --scope meta "
                "--sin-metadatos --rag-dir rag_storage_meta\n"
                "o analiza solo las palabras clave con --fuente keywords."
            )
        noise = 0
        for entity, article_ids in self._reader.read().entity_to_articles.items():
            key = self._resolver.group_key(entity)
            if self._noise.is_noise(key):
                noise += 1
                continue
            hits = article_ids & allowed
            for article_id in hits:
                concepts[article_id].add(key)
            surfaces[key][entity] += len(hits)
        return noise

    def _add_keywords(self, articles: list[Article], concepts, surfaces) -> int:
        noise = 0
        for article in articles:
            for keyword in KEYWORD_SPLIT.split(article.keywords or ""):
                keyword = keyword.strip().strip(".").strip()
                if not keyword or len(keyword) > 80:
                    continue
                key = self._resolver.group_key(keyword)
                if self._noise.is_noise(key):
                    noise += 1
                    continue
                concepts[article.id].add(key)
                surfaces[key][keyword] += 1
        return noise

    # ------------------------------------------------------------------ filtros
    def _drop_sparse_years(self, years: dict[str, int], concepts) -> dict[str, set[str]]:
        """Quita los años con tan pocos artículos que su prevalencia no significa nada."""
        minimum = self._params.get("min_articulos_anio", 10)
        per_year = Counter(years.values())
        return {a: c for a, c in concepts.items()
                if a in years and per_year[years[a]] >= minimum}

    def _find_hubs(self, concepts) -> list[tuple[str, int]]:
        """Conceptos presentes en demasiados artículos para distinguir temas.

        En el grafo de coocurrencia un concepto así conecta todo con todo y
        funde las comunidades en una sola, así que no participa en ella. Pero
        puede ser un tema real ("Gamificación"), de modo que conserva su serie.
        """
        limit = self._params.get("max_fraccion_concepto", 0.15) * len(concepts)
        df = Counter(c for cs in concepts.values() for c in cs)
        return sorted(((c, n) for c, n in df.items() if n > limit),
                      key=lambda item: -item[1])

    @staticmethod
    def _pick_label(forms: Counter) -> str:
        """La variante más frecuente; a igualdad, la más corta."""
        return max(forms.items(), key=lambda item: (item[1], -len(item[0])))[0]
