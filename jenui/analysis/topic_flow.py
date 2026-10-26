"""Evolución estructural de los topics: nacimientos, fusiones y divisiones."""
from __future__ import annotations

from dataclasses import dataclass, field

from jenui.analysis.concept_source import ConceptCorpus
from jenui.analysis.topic_detector import Topic, TopicDetector


@dataclass
class WindowTopic:
    """Un topic detectado dentro de una ventana temporal."""

    id: str
    window: str                 # "1997–2001"
    label: str
    concepts: set[str]
    n_articles: int
    topic_global: str | None    # topic global al que más se parece
    events: list[str] = field(default_factory=list)


@dataclass
class FlowLink:
    source: str
    target: str
    shared: int                 # conceptos en común
    jaccard: float


@dataclass
class TopicFlow:
    windows: list[str]
    nodes: list[WindowTopic]
    links: list[FlowLink]


class TopicFlowBuilder:
    """Detecta topics por ventanas de años y los enlaza entre ventanas.

    Los topics globales responden a *cuánto* se habla de cada tema; esto
    responde a *cómo cambia su estructura*: un tema que nace de otro, dos que
    se funden, uno que se divide. Es el método habitual de seguimiento de
    comunidades en el tiempo: comunidades por ventana y emparejamiento entre
    ventanas consecutivas por solapamiento de conceptos (Jaccard).

    El Jaccard se mide sobre el **vocabulario común** a las dos ventanas: un
    concepto que en la ventana anterior aún no existía (o que ya no se usa en
    la siguiente) no puede indicar ni continuidad ni ruptura, y contarlo
    hundiría la similitud de cualquier tema que se renueva.

    Las ventanas se alinean con el **último** año, para que la más reciente
    esté completa; si la primera queda muy corta, se une a la siguiente.
    """

    def __init__(self, detector: TopicDetector, window: int = 5,
                 jaccard_threshold: float = 0.1, min_articles: int = 5) -> None:
        self._detector = detector
        self._window = window
        self._threshold = jaccard_threshold
        self._min_articles = min_articles

    def build(self, corpus: ConceptCorpus, global_topics: list[Topic]) -> TopicFlow:
        spans = self.windows(corpus.years)
        layers: list[list[WindowTopic]] = []
        for number, (start, end) in enumerate(spans, start=1):
            name = f"{start}–{end}"
            ids = [a for a, y in corpus.article_year.items() if start <= y <= end]
            detected = self._detector.detect(corpus, ids, prefix=f"V{number}.")
            layers.append([
                WindowTopic(t.id, name, t.label, set(t.concepts), len(t.articles),
                            self._closest(t, global_topics))
                for t in detected if len(t.articles) >= self._min_articles
            ])

        links = []
        for current, following in zip(layers, layers[1:]):
            common = (set().union(*(n.concepts for n in current))
                      & set().union(*(n.concepts for n in following)))
            for a in current:
                for b in following:
                    left, right = a.concepts & common, b.concepts & common
                    shared = len(left & right)
                    if not shared:
                        continue
                    jaccard = shared / len(left | right)
                    if jaccard >= self._threshold:
                        links.append(FlowLink(a.id, b.id, shared, jaccard))

        self._mark_events(layers, links)
        names = [f"{s}–{e}" for s, e in spans]
        return TopicFlow(names, [n for layer in layers for n in layer], links)

    def windows(self, years: list[int]) -> list[tuple[int, int]]:
        if not years:
            return []
        first, last = years[0], years[-1]
        spans = []
        end = last
        while end >= first:
            spans.append((max(first, end - self._window + 1), end))
            end -= self._window
        spans.reverse()
        if len(spans) > 1 and spans[0][1] - spans[0][0] + 1 < (self._window + 1) // 2:
            spans[1] = (spans[0][0], spans[1][1])
            spans.pop(0)
        return spans

    @staticmethod
    def _closest(topic: Topic, global_topics: list[Topic]) -> str | None:
        concepts = set(topic.concepts)
        best, best_score = None, 0.0
        for candidate in global_topics:
            union = concepts | set(candidate.concepts)
            score = len(concepts & set(candidate.concepts)) / len(union) if union else 0.0
            if score > best_score:
                best, best_score = candidate.id, score
        return best

    @staticmethod
    def _mark_events(layers: list[list[WindowTopic]], links: list[FlowLink]) -> None:
        incoming: dict[str, int] = {}
        outgoing: dict[str, int] = {}
        for link in links:
            outgoing[link.source] = outgoing.get(link.source, 0) + 1
            incoming[link.target] = incoming.get(link.target, 0) + 1
        last = len(layers) - 1
        for position, layer in enumerate(layers):
            for node in layer:
                if position > 0 and not incoming.get(node.id):
                    node.events.append("nace")
                if position < last and not outgoing.get(node.id):
                    node.events.append("desaparece")
                if incoming.get(node.id, 0) > 1:
                    node.events.append("fusión")
                if outgoing.get(node.id, 0) > 1:
                    node.events.append("se divide")
