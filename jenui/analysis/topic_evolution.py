"""Series temporales y clasificación de topics y conceptos."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from jenui.analysis.concept_source import ConceptCorpus

#: Clases de topic, en el orden en que se comprueban.
CLASSES = [
    "emergente reciente",
    "emergente consolidado",
    "pasajero",
    "recurrente",
    "en declive",
    "intermitente",
    "esporádico",
]

DEFAULT_CLASSIFICATION = {
    "min_articulos_topic": 5,
    "umbral_inicio": 0.2,
    "anios_previos": 3,
    "anios_consolidacion": 4,
    "cobertura_minima": 0.7,
    "nivel_consolidado": 0.4,
    "nivel_apagado": 0.25,
    "duracion_max_pasajero": 6,
    "anios_min_recurrente": 10,
}


@dataclass
class TopicSeries:
    """Presencia de un topic año a año."""

    years: list[int]
    counts: list[int]           # artículos del topic
    share: list[float]          # fracción de los artículos del año
    smooth: list[float]         # ``share`` con media móvil centrada


@dataclass
class TopicProfile:
    """Clase de un topic y las métricas que la justifican."""

    clase: str
    tendencia: str = "estable"
    anio_primero: int | None = None     # primer año con algún artículo
    anio_inicio: int | None = None      # primer año con presencia apreciable
    anio_pico: int | None = None
    pico: float = 0.0                   # prevalencia suavizada máxima
    nivel_reciente: float = 0.0         # media de los 3 últimos años / pico
    cobertura: float = 0.0              # años con artículos desde el inicio
    largo_recorrido: bool = False       # >= anios_min_recurrente desde el inicio


@dataclass
class EmergingConcept:
    """Un concepto que aparece por primera vez en un año, y qué fue de él."""

    concept: str
    label: str
    anio: int
    articulos: int                      # en total
    articulos_despues: int              # en los años siguientes al de aparición
    anios_presente_despues: int
    anios_despues: int
    estado: str                         # consolidado | reciente | intermitente | puntual
    pioneros: list[str] = field(default_factory=list)


class TopicEvolution:
    """Mide cómo evoluciona cada topic y lo clasifica.

    La medida base es la **prevalencia**: fracción de los artículos de un año
    que tratan el topic. Normalizar es imprescindible porque el congreso ha
    tenido entre 45 y 95 artículos al año. Con ~60 artículos al año un solo
    artículo mueve la prevalencia casi dos puntos, así que se clasifica sobre
    la serie suavizada (media móvil centrada de ``ventana`` años).

    Todos los umbrales son **relativos al pico de cada topic**: un tema
    minoritario pero constante es tan recurrente como uno mayoritario.
    """

    def __init__(self, corpus: ConceptCorpus, window: int = 3,
                 params: dict | None = None) -> None:
        self._corpus = corpus
        self._window = max(1, window)
        self.params = {**DEFAULT_CLASSIFICATION, **(params or {})}
        self.years = corpus.years
        totals = corpus.year_totals()
        self._totals = [totals[y] for y in self.years]

    # ------------------------------------------------------------------ series
    def series(self, article_ids: set[str]) -> TopicSeries:
        per_year = Counter(self._corpus.article_year[a] for a in article_ids
                           if a in self._corpus.article_year)
        counts = [per_year[y] for y in self.years]
        share = [c / t if t else 0.0 for c, t in zip(counts, self._totals)]
        return TopicSeries(self.years, counts, share, self._smooth(share))

    def _smooth(self, values: list[float]) -> list[float]:
        half = self._window // 2
        return [float(np.mean(values[max(0, i - half):i + half + 1]))
                for i in range(len(values))]

    # ----------------------------------------------------------- clasificación
    def classify(self, series: TopicSeries) -> TopicProfile:
        """Clasifica un topic según la forma de su serie.

        En orden (gana la primera que encaja):

        * **emergente reciente** — emerge (ver abajo) hace menos de
          ``anios_consolidacion`` años: aún no se puede saber si cuajará.
        * **emergente consolidado** — emerge y desde entonces está presente en
          al menos ``cobertura_minima`` de los años y sigue vivo (nivel de los
          tres últimos años >= ``nivel_consolidado`` del pico).
        * **pasajero** — se apagó (nivel reciente < ``nivel_apagado``) tras una
          vida activa corta (<= ``duracion_max_pasajero`` años). COVID-19.
        * **recurrente** — presente en al menos ``cobertura_minima`` de los años
          durante ``anios_min_recurrente`` o más, y no apagado.
        * **en declive** — se apagó tras una vida larga.
        * **intermitente** — el resto.

        Un topic *emerge* si su inicio (primer año con prevalencia >=
        ``umbral_inicio`` del pico) llega al menos ``anios_previos`` años
        después del comienzo de los datos y antes apenas existía (media previa
        < 10 % del pico). Lo presente desde el primer año no puede ser
        emergente: no sabemos qué había antes.
        """
        p = self.params
        counts, smooth, years = series.counts, series.smooth, series.years
        present = [i for i, c in enumerate(counts) if c > 0]
        peak = max(smooth) if smooth else 0.0
        if sum(counts) < p["min_articulos_topic"] or len(present) < 2 or peak == 0:
            return TopicProfile(
                "esporádico",
                anio_primero=years[present[0]] if present else None,
                pico=peak,
            )

        threshold = p["umbral_inicio"] * peak
        onset = next(i for i, (c, v) in enumerate(zip(counts, smooth))
                     if c > 0 and v >= threshold)
        before = smooth[:onset]
        emergent = (onset >= p["anios_previos"]
                    and (not before or float(np.mean(before)) < 0.1 * peak))

        since = counts[onset:]
        coverage = sum(c > 0 for c in since) / len(since)
        first = present[0]
        coverage_all = sum(c > 0 for c in counts[first:]) / len(counts[first:])
        recent = float(np.mean(smooth[-3:])) / peak
        active = [i for i, v in enumerate(smooth) if v >= threshold]
        duration = active[-1] - active[0] + 1

        if emergent and len(since) < p["anios_consolidacion"]:
            clase = "emergente reciente"
        elif emergent and coverage >= p["cobertura_minima"] and recent >= p["nivel_consolidado"]:
            clase = "emergente consolidado"
        elif recent < p["nivel_apagado"] and duration <= p["duracion_max_pasajero"]:
            clase = "pasajero"
        elif (len(counts) - first >= p["anios_min_recurrente"]
              and coverage_all >= p["cobertura_minima"]
              and recent >= p["nivel_apagado"]):
            clase = "recurrente"
        elif recent < p["nivel_apagado"]:
            clase = "en declive"
        else:
            clase = "intermitente"

        return TopicProfile(
            clase=clase,
            tendencia=self._trend(years[first:], smooth[first:]),
            anio_primero=years[first],
            anio_inicio=years[onset],
            anio_pico=years[int(np.argmax(smooth))],
            pico=peak,
            nivel_reciente=recent,
            cobertura=coverage,
            largo_recorrido=len(since) >= p["anios_min_recurrente"],
        )

    @staticmethod
    def _trend(years: list[int], smooth: list[float]) -> str:
        """Pendiente de la recta de regresión, como cambio por década relativo a la media.

        Se calcula desde la primera aparición: medida sobre todo el periodo, un
        tema pasajero reciente saldría "creciente" por los ceros previos.
        """
        mean = float(np.mean(smooth))
        if len(years) < 3 or mean == 0:
            return "estable"
        slope = float(np.polyfit(years, smooth, 1)[0])
        change = slope * 10 / mean
        if change > 0.3:
            return "creciente"
        if change < -0.3:
            return "decreciente"
        return "estable"

    # ------------------------------------------------------ conceptos emergentes
    def emerging_concepts(self, min_articles: int) -> list[EmergingConcept]:
        """Conceptos por año de primera aparición, con su recorrido posterior.

        Responde directamente a "qué apareció en tal año y si luego cuajó",
        a un nivel más fino que los topics. Se omiten los conceptos que ya
        están en los primeros ``anios_previos`` años, porque ahí no se puede
        distinguir lo nuevo de lo que ya existía.

        Estado:

        * **consolidado** — presente en al menos la mitad de los años
          siguientes, y en tres o más (o en todos, si han pasado menos);
        * **reciente** — han pasado menos de dos años para juzgarlo;
        * **puntual** — sin artículos tras su año de aparición;
        * **intermitente** — el resto.
        """
        corpus = self._corpus
        skip = self.params["anios_previos"]
        index = {y: i for i, y in enumerate(self.years)}
        result = []
        for concept, articles in corpus.concept_articles().items():
            if len(articles) < min_articles:
                continue
            per_year = Counter(corpus.article_year[a] for a in articles)
            first = min(per_year)
            if index[first] < skip:
                continue
            later = [y for y in self.years if y > first]
            present_after = sum(per_year[y] > 0 for y in later)
            articles_after = sum(per_year[y] for y in later)
            if len(later) < 2:
                estado = "reciente"
            elif articles_after == 0:
                estado = "puntual"
            elif (present_after / len(later) >= 0.5
                  and present_after >= min(3, len(later))):
                estado = "consolidado"
            else:
                estado = "intermitente"
            pioneers = sorted(a for a in articles if corpus.article_year[a] == first)
            result.append(EmergingConcept(
                concept, corpus.label(concept), first, len(articles),
                articles_after, present_after, len(later), estado, pioneers,
            ))
        result.sort(key=lambda e: (e.anio, -e.articulos_despues, e.label))
        return result
