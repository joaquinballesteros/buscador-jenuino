"""Corrector ortográfico de consultas, basado en el vocabulario del corpus."""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from jenui.domain.article import Article

_TOKEN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)   # palabras (sin dígitos)


def _strip_accents(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word)
                   if not unicodedata.combining(c))


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

    Dos vocabularios: los candidatos salen de títulos, resúmenes y palabras
    clave (lo más cuidado), pero una palabra se da por buena si además aparece
    en el cuerpo de al menos ``min_body_docs`` artículos. Sin eso, palabras
    corrientes que no salen en ningún resumen se "corregían" a otra parecida
    ("delegar" -> "desplegar"). Entre los candidatos gana el **más parecido**;
    la frecuencia solo desempata ("univesitario" -> "universitario", no
    "universitaria").
    """

    def __init__(self, vocabulary: Counter, min_length: int = 4,
                 cutoff: float = 0.82, known: set[str] | None = None) -> None:
        self._freq = vocabulary
        self._vocab = set(vocabulary) | (known or set())
        self._min_length = min_length
        self._cutoff = cutoff
        # buckets por longitud para acotar la búsqueda de candidatos
        self._by_length: dict[int, list[str]] = {}
        for word in self._vocab:
            self._by_length.setdefault(len(word), []).append(word)

    # ------------------------------------------------------------ construcción
    @classmethod
    def from_articles(cls, articles, min_body_docs: int = 3, **kwargs) -> "SpellCorrector":
        freq: Counter = Counter()
        body_docs: Counter = Counter()
        for article in articles:
            text = " ".join(filter(None, (
                article.title, article.keywords, article.abstract
            )))
            freq.update(m.group().lower() for m in _TOKEN.finditer(text))
            body_docs.update({m.group().lower() for m in _TOKEN.finditer(article.text or "")})
        known = {w for w, n in body_docs.items() if n >= min_body_docs}
        return cls(freq, known=known, **kwargs)

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
        # solo candidatos que no sean a su vez erratas sueltas del corpus, y
        # comparados sin tildes: con ellas "evaluación" quedaba por debajo del
        # umbral para "evaluasion" y ganaba "evaluation"
        by_plain: dict[str, list[str]] = {}
        for w in candidates:
            if self._freq[w] >= 2:
                by_plain.setdefault(_strip_accents(w), []).append(w)
        plain = _strip_accents(low)
        matches = difflib.get_close_matches(plain, list(by_plain), n=5, cutoff=self._cutoff)
        if not matches:
            return word
        # el más parecido; la frecuencia en el corpus desempata
        return max((w for m in matches for w in by_plain[m]), key=lambda w: (
            round(difflib.SequenceMatcher(None, plain, _strip_accents(w)).ratio(), 3),
            self._freq[w]))
