"""Corrector ortográfico de consultas, basado en el vocabulario del corpus."""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass

from jenui.domain.article import Article

_TOKEN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)   # palabras (sin dígitos)


@dataclass
class Correction:
    """Resultado de corregir una consulta."""

    original: str
    corrected: str

    @property
    def changed(self) -> bool:
        return self.corrected.lower() != self.original.lower()


class SpellCorrector:
    """Corrige erratas de la consulta hacia palabras que existen en el corpus.

    Es **específico del dominio**: el vocabulario se construye con las palabras
    de los propios artículos (títulos, resúmenes, palabras clave), así que
    corrige 'gamifiacion' -> 'gamificación' pero **no** toca términos técnicos
    como 'scrum' o 'abp', que un diccionario español genérico marcaría como
    errores. La frecuencia en el corpus desempata hacia lo más habitual.

    Conservador por diseño: solo actúa sobre palabras que **no** están en el
    vocabulario, suficientemente largas y con un candidato muy parecido. Ante la
    duda, deja la palabra como está: la búsqueda semántica ya tolera lo leve.
    """

    def __init__(self, vocabulary: Counter, min_length: int = 4,
                 cutoff: float = 0.82) -> None:
        self._freq = vocabulary
        self._vocab = set(vocabulary)
        self._min_length = min_length
        self._cutoff = cutoff
        # buckets por longitud para acotar la búsqueda de candidatos
        self._by_length: dict[int, list[str]] = {}
        for word in self._vocab:
            self._by_length.setdefault(len(word), []).append(word)

    # ------------------------------------------------------------ construcción
    @classmethod
    def from_articles(cls, articles, **kwargs) -> "SpellCorrector":
        freq: Counter = Counter()
        for article in articles:
            text = " ".join(filter(None, (
                article.title, article.keywords, article.abstract
            )))
            freq.update(m.group().lower() for m in _TOKEN.finditer(text))
        return cls(freq, **kwargs)

    # ------------------------------------------------------------------ corregir
    def correct(self, query: str) -> Correction:
        parts = re.split(r"(\W+)", query)          # conserva separadores
        out = [self._fix(p) if p and _TOKEN.fullmatch(p) else p for p in parts]
        return Correction(original=query, corrected="".join(out))

    def _fix(self, word: str) -> str:
        low = word.lower()
        if len(low) < self._min_length or low in self._vocab:
            return word
        candidates: list[str] = []
        for length in range(len(low) - 2, len(low) + 3):
            candidates.extend(self._by_length.get(length, ()))
        matches = difflib.get_close_matches(low, candidates, n=5, cutoff=self._cutoff)
        if not matches:
            return word
        # entre los más parecidos, el más frecuente en el corpus
        best = max(matches, key=lambda w: self._freq[w])
        return best if self._freq[best] >= 2 else word
