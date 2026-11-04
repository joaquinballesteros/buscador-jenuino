"""Detección y reparación de texto ilegible extraído de los PDFs."""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from jenui.domain.article import Article

_WORD = re.compile(r"[a-záéíóúñüç]{3,}")
#: Caracteres de control que algunos PDFs usan en lugar de espacios.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class TextQuality:
    """Decide si un texto es legible y repara los defectos de fuente conocidos.

    En las actas antiguas (sobre todo 2000-2009) hay PDFs con fuentes mal
    codificadas. Su texto, y el resumen que aenui.org publica en la ficha (que
    sale del mismo PDF), llega de varias formas:

    * **cifrado**: cada carácter desplazado 29 posiciones (``/HFFLRQHV`` es
      ``Lecciones``), con las vocales acentuadas en otra tabla;
    * **sustitución** constante (``Me#oras en la asi/natura``);
    * letras duplicadas, perdidas o desordenadas (``siisstteemmaa``,
      ``redes de olorión``).

    La legibilidad es la fracción de palabras que existen en el **vocabulario
    del propio corpus** (las que aparecen en al menos ``min_docs`` artículos):
    la basura de fuente casi nunca se repite tanto. Medido sobre el corpus, la
    distribución es bimodal: los textos limpios superan 0,85 y los rotos
    quedan por debajo de 0,75.

    El cifrado se invierte; la sustitución, cuando el título roto mide lo
    mismo que el limpio de la ficha, se deshace con la tabla que se aprende
    comparándolos. Para lo demás se recurre al cuerpo del artículo, que a
    menudo se extrajo bien aunque la ficha no (ver :meth:`best_abstract`).
    """

    LEGIBLE = 0.85
    MIN_WORDS = 15
    MIN_GAIN = 0.1

    _SHIFT = 29
    _ACCENTS = {"i": "á", "p": "é", "t": "í", "y": "ó", "~": "ú", "q": "ñ", "l": "ü"}

    def __init__(self, vocabulary: set[str]) -> None:
        self._vocabulary = vocabulary

    @classmethod
    def from_articles(cls, articles: Iterable[Article], min_docs: int = 8,
                      body_chars: int = 20000) -> "TextQuality":
        df: Counter = Counter()
        for article in articles:
            df.update(set(cls._words(article.abstract))
                      | set(cls._words((article.text or "")[:body_chars])))
        return cls({w for w, n in df.items() if n >= min_docs})

    # ---------------------------------------------------------------- medida
    def legibility(self, text: str | None) -> float:
        """Fracción de palabras del vocabulario (0 si el texto es muy corto)."""
        words = self._words(text)
        if len(words) < self.MIN_WORDS:
            return 0.0
        return sum(w in self._vocabulary for w in words) / len(words)

    def is_legible(self, text: str | None) -> bool:
        return self.legibility(text) >= self.LEGIBLE

    # ------------------------------------------------------------ reparación
    @staticmethod
    def clean_controls(text: str | None) -> str:
        return _CONTROL.sub(" ", text or "")

    @classmethod
    def repair_cipher(cls, text: str | None) -> str:
        """Invierte el desplazamiento de 29 posiciones, línea a línea.

        Solo se tocan las líneas cifradas: casi sin minúsculas antes y casi
        todo minúsculas después. Así un título cifrado sobre un resumen normal
        se arregla sin estropear el resto.
        """
        lines = []
        for line in (text or "").split("\n"):
            decoded = cls._unshift(line)
            if cls._lower_ratio(line) < 0.3 and cls._lower_ratio(decoded) > 0.6:
                line = decoded
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def repair_substitution(text: str | None, title: str | None) -> str:
        """Deshace una sustitución de caracteres constante en el documento.

        La primera línea del texto suele ser el título. Si mide lo mismo que el
        título limpio de la ficha y coincide en buena parte, cada diferencia
        enseña una regla (``#`` → ``j``). Se descartan las reglas
        contradictorias y se aplica la tabla al resto del texto.
        """
        text, title = text or "", (title or "").strip()
        first = text.split("\n", 1)[0].strip()
        if not title or len(first) != len(title):
            return text
        same = sum(a == b for a, b in zip(first, title))
        if same < 0.5 * len(title):
            return text
        rules: dict[str, set[str]] = {}
        for broken, clean in zip(first, title):
            if broken != clean:
                rules.setdefault(broken, set()).add(clean)
        table = {k: next(iter(v)) for k, v in rules.items() if len(v) == 1}
        return "".join(table.get(ch, ch) for ch in text)

    def best_abstract(self, current: str | None, body: str | None,
                      title: str | None = None, intro_chars: int = 1500) -> str:
        """El resumen más legible entre las variantes del artículo.

        Si el actual ya es legible se respeta. Si no, se prueban el actual
        reparado (cifrado y sustitución) y el cuerpo desde su "Resumen" (o
        desde el principio), y gana el más legible siempre que mejore al
        actual en al menos ``MIN_GAIN``.
        """
        current = self.clean_controls(current).strip()
        if self.is_legible(current):
            return current
        candidates = [
            self.repair_cipher(current),
            self.repair_substitution(current, title),
            self._intro(self.repair_cipher(self.clean_controls(body)), intro_chars),
        ]
        best = max(candidates, key=self.legibility)
        if self.legibility(best) >= self.legibility(current) + self.MIN_GAIN:
            return best.strip()
        return current

    def best_body(self, body: str | None, sample_chars: int = 6000) -> str:
        """El cuerpo con el cifrado invertido, si eso lo hace más legible."""
        body = body or ""
        if self.is_legible(body[:sample_chars]):
            return body
        repaired = self.repair_cipher(self.clean_controls(body))
        if (self.legibility(repaired[:sample_chars])
                >= self.legibility(body[:sample_chars]) + self.MIN_GAIN):
            return repaired
        return body

    # ------------------------------------------------------------------ interno
    @staticmethod
    def _words(text: str | None) -> list[str]:
        return _WORD.findall((text or "").lower())

    @staticmethod
    def _intro(body: str, chars: int) -> str:
        """Comienzo del cuerpo, saltando la cabecera hasta "Resumen" si está."""
        match = re.search(r"(?i)\b\w?esumen\b[\s.:—-]*", body[:5000])
        start = match.end() if match else 0
        return re.sub(r"\s+", " ", body[start:start + chars]).strip()

    @classmethod
    def _unshift(cls, text: str) -> str:
        out = []
        for ch in text:
            if ch in cls._ACCENTS:
                out.append(cls._ACCENTS[ch])
            elif 33 <= ord(ch) <= 93:
                out.append(chr(ord(ch) + cls._SHIFT))
            else:
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _lower_ratio(text: str) -> float:
        letters = [c for c in text if c.isalpha() or c in "!\"#$%&'()*+,-./0123456789:;<=>?@[\\]"]
        if len(letters) < 8:
            return 1.0
        return sum(c.islower() for c in letters) / len(letters)
