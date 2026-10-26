"""Red de citas entre artículos de JENUI, para validar la consolidación."""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CitationStats:
    """Lo que las citas dicen de un topic."""

    citas_internas: int = 0                 # citas de un artículo del topic a otro
    mas_citados: list[tuple[str, int]] = field(default_factory=list)
    posteriores_con_referencias: int = 0
    posteriores_que_citan_pioneros: int = 0

    @property
    def fraccion_citan_pioneros(self) -> float | None:
        if not self.posteriores_con_referencias:
            return None
        return self.posteriores_que_citan_pioneros / self.posteriores_con_referencias


class CitationNetwork:
    """Citas internas leídas de ``fuentes/referencias_jenui.csv``.

    Es una prueba **independiente de la frecuencia**: que un tema se escriba
    mucho no garantiza que sea una línea de trabajo; que los artículos
    posteriores citen a los primeros, sí. Por eso se mide, para cada topic
    con año de inicio, qué fracción de los artículos posteriores cita a los
    *pioneros* (los de los tres primeros años).

    Solo cuentan como posteriores los artículos cuyas referencias se han
    extraído (los que aparecen como citantes en el CSV), para no confundir
    "no cita" con "no sabemos".
    """

    def __init__(self, edges: list[tuple[str, str]], citing: set[str]) -> None:
        self._edges = edges
        self._citing = citing
        self._cites: dict[str, set[str]] = {}
        for source, target in edges:
            self._cites.setdefault(source, set()).add(target)

    @classmethod
    def load(cls, path: Path) -> "CitationNetwork | None":
        if not path.exists():
            return None
        edges, citing = [], set()
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                source = Path(row.get("archivo", "")).stem
                if not source:
                    continue
                citing.add(source)
                target = (row.get("jenui_citado") or "").strip()
                if target and target != source:
                    edges.append((source, target))
        return cls(edges, citing)

    @property
    def n_edges(self) -> int:
        return len(self._edges)

    @property
    def n_citing(self) -> int:
        return len(self._citing)

    def topic_stats(self, articles: set[str], article_year: dict[str, int],
                    onset: int | None, pioneer_years: int = 3) -> CitationStats:
        received: Counter = Counter()
        internal = 0
        for source in articles:
            for target in self._cites.get(source, ()):
                if target in articles:
                    internal += 1
                    received[target] += 1

        stats = CitationStats(citas_internas=internal,
                              mas_citados=received.most_common(3))
        if onset is None:
            return stats
        limit = onset + pioneer_years - 1
        pioneers = {a for a in articles if article_year.get(a, limit + 1) <= limit}
        later = [a for a in articles
                 if article_year.get(a, 0) > limit and a in self._citing]
        stats.posteriores_con_referencias = len(later)
        stats.posteriores_que_citan_pioneros = sum(
            1 for a in later if self._cites.get(a, set()) & pioneers
        )
        return stats
