"""Extracción de la lista de referencias bibliográficas de un artículo."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from jenui.ingestion.text_normalizer import TextNormalizer


@dataclass
class Reference:
    numero: int
    texto: str
    metodo: str          # "numerada" (fiable) o "bloques" (aproximada)


class ReferenceExtractor:
    """Saca las referencias del final de un PDF de las actas, una por entrada.

    Dos estrategias, de más a menos fiable:

    * **numerada** — la bibliografía usa marcadores ``[1]``, ``[2]``…: se
      parte por ellos. Es lo habitual desde ~2013.
    * **bloques** — sin marcadores (actas antiguas escaneadas con OCR, o
      estilos sin numerar): cada bloque de texto del PDF se toma como una
      referencia, uniendo los que parecen continuación del anterior. Es
      aproximada: puede juntar o partir alguna entrada.
    """

    _HEADING = re.compile(
        r"(?:^|\n)[ \t]*(?:\d+\.?\s*)?"
        r"(Referencias(?:\s+bibliogr[aá]ficas)?|Bibliograf[ií]a|References)"
        r"[ \t]*(?:\n|$)",
        re.IGNORECASE,
    )
    _MARKER = re.compile(r"(?:^|\n)\s*\[(\d{1,3})\]\s*")
    # pies y cabeceras de página que se cuelan entre referencias
    _NOISE = re.compile(
        r"^\s*(?:Actas de las Jenui.*|P[aá]ginas:.*|\d{1,4}|"
        r".*Jornadas (?:sobre|de) Ense[ñn]anza Universitaria de la Inform[aá]tica.{0,40})\s*$",
        re.IGNORECASE,
    )

    # pie de página incrustado dentro de un bloque de texto
    _FOOTER = re.compile(
        r"(?:\d{1,4}\s*)?Actas de las Jenui, vol\. \d+\. \d{4}\.?[^\n]{0,20}"
        r"|P[aá]ginas:\s*\d+\s*-\s*\d+",
        re.IGNORECASE,
    )

    def __init__(self, min_position: float = 0.4) -> None:
        self._min_position = min_position

    def extract(self, path: Path) -> list[Reference]:
        document = fitz.open(path)
        try:
            pages = [
                [block[4] for block in page.get_text("blocks") if block[6] == 0]
                for page in document
            ]
            text = self._join(pages)
            start = self._find_start(text)
            if start is not None:
                numbered = self._split_numbered(text[start:])
                if numbered:
                    return numbered
            # sin numeración: los bloques del PDF no siempre son párrafos (OCR),
            # así que se rehacen a partir de la posición de cada línea
            text = self._join([self._paragraphs(page) for page in document])
        finally:
            document.close()
        start = self._find_start(text)
        return self._split_blocks(text[start:]) if start is not None else []

    def _join(self, pages: list[list[str]]) -> str:
        # cabeceras/pies: bloques que se repiten en varias páginas (salvo números)
        repeated = Counter(self._skeleton(b) for page in pages for b in set(page))
        blocks = [
            self._clean(b) for page in pages for b in page
            if len(pages) < 3 or repeated[self._skeleton(b)] < 3
        ]
        blocks = [b for b in blocks if b and not self._NOISE.match(b)]
        return "\n\n".join(blocks)

    @staticmethod
    def _paragraphs(page) -> list[str]:
        """Párrafos de la página: columna a columna, cortando donde hay hueco vertical."""
        lines = []          # (columna, y0, y1, x0, texto)
        middle = page.rect.width / 2
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                garbage = sum(not (c.isascii() or c.isalpha()) for c in text)
                if text and garbage < len(text) * 0.3:     # capa OCR ilegible
                    x0, y0, x1, y1 = line["bbox"]
                    lines.append((int(x0 >= middle - 10), y0, y1, x0, text))
        lines.sort(key=lambda l: (l[0], round(l[1] / 3), l[3]))
        # fragmentos a la misma altura forman una sola línea
        merged: list[list] = []
        for col, y0, y1, x0, text in lines:
            if merged and merged[-1][0] == col and abs(merged[-1][1] - y0) < 3:
                merged[-1][4] += " " + text
                merged[-1][2] = max(merged[-1][2], y1)
            else:
                merged.append([col, y0, y1, x0, text])
        steps = sorted(b[1] - a[1] for a, b in zip(merged, merged[1:])
                       if a[0] == b[0] and b[1] > a[1])
        step = steps[len(steps) // 2] if steps else 12     # interlineado típico
        paragraphs: list[list[str]] = []
        previous = None
        for line in merged:
            if previous is None or line[0] != previous[0] or line[1] - previous[1] > step * 1.5:
                paragraphs.append([])
            paragraphs[-1].append(line[4])
            previous = line
        return ["\n".join(p) for p in paragraphs]

    # ---------------------------------------------------------------- pasos
    @staticmethod
    def _skeleton(block: str) -> str:
        return re.sub(r"\d+", "#", block.strip())

    @classmethod
    def _clean(cls, text: str) -> str:
        text = re.sub(r"(\w)-[ \t]*\n(?=[a-zñáéíóú])", r"\1", text)   # pala- bra
        text = TextNormalizer.clean(text)
        text = re.sub(r"[´ˊ]ı|ı[´ˊ]", "í", text)     # acento sobre i sin punto
        text = cls._FOOTER.sub(" ", text)
        return text.strip()

    def _find_start(self, text: str) -> int | None:
        """Final del encabezado de bibliografía.

        Si alguno va seguido de ``[1]`` es inequívoco y se toma esté donde
        esté (hay PDFs que guardan los bloques fuera de orden de lectura). Si
        no, el último que caiga en la parte final del documento.
        """
        matches = list(self._HEADING.finditer(text))
        for match in reversed(matches):
            if re.match(r"\s*\[1\]", text[match.end():]):
                return match.end()
        start = None
        for match in matches:
            if match.start() >= len(text) * self._min_position:
                start = match.end()
        return start

    def _split_numbered(self, bib: str) -> list[Reference]:
        """Parte por ``[n]`` si los marcadores forman una secuencia 1, 2, 3…"""
        markers, expected = [], 1
        for match in self._MARKER.finditer(bib):
            if int(match.group(1)) == expected:
                markers.append(match)
                expected += 1
        if len(markers) < 2:
            return []
        refs = []
        for i, match in enumerate(markers):
            end = markers[i + 1].start() if i + 1 < len(markers) else len(bib)
            texto = self._finish(bib[match.end():end])
            if texto:
                refs.append(Reference(int(match.group(1)), texto, "numerada"))
        return refs

    # inicio típico de una referencia: "Apellido, A.", "A. Apellido", "Nombre Apellido,"
    _AUTHOR_START = re.compile(
        r"^(?:[A-ZÁÉÍÓÚÑ][\w'’-]+,\s*[A-ZÁÉÍÓÚ][a-z]?\."
        r"|[A-ZÁÉÍÓÚ]\.\s*(?:[A-ZÁÉÍÓÚ]\.\s*)?[A-ZÁÉÍÓÚ][\w'’-]+"
        r"|[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+(?:[A-Z]\.\s*)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ-]+[,.:])"
    )

    def _split_blocks(self, bib: str) -> list[Reference]:
        """Sin numeración: corta donde empieza bloque o donde, tras un punto, empieza un autor."""
        entries: list[list[str]] = []
        for block in bib.split("\n\n"):
            for k, line in enumerate(block.split("\n")):
                line = re.sub(r"^[\[(]?\d{1,3}[\])]?\.?\s+", "", line.strip())   # n.º suelto
                if not line or (len(line) < 6 and not entries):
                    continue          # restos de OCR, números de columna…
                previous = entries[-1][-1] if entries else ""
                new_entry = not entries or (
                    line[0].isupper()
                    and (k == 0 and not previous.endswith((",", "-", " y", " and"))
                         or previous.endswith(".") and self._AUTHOR_START.match(line))
                )
                if new_entry:
                    entries.append([line])
                else:
                    entries[-1].append(line)
        texts = [self._finish("\n".join(e)) for e in entries]
        texts = [t for t in texts if len(t) >= 15]
        return [Reference(i, t, "bloques") for i, t in enumerate(texts, 1)]

    @staticmethod
    def _finish(text: str, max_chars: int = 600) -> str:
        text = TextNormalizer.collapse(text)
        text = re.sub(r"([a-zñáéíóú])- (?=[a-zñáéíóú])", r"\1", text)   # pala- bra
        # la última suele arrastrar apéndices o texto posterior: se recorta
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + " […]"
        return text


class JenuiCitationMatcher:
    """Detecta si una referencia cita un artículo de JENUI y, si se puede, cuál.

    El emparejamiento busca el título del artículo citado (normalizado: sin
    acentos, mayúsculas ni puntuación) dentro del texto de la referencia.
    """

    _VENUE = re.compile(
        r"JENUI|Jornadas (?:sobre|de) Ense[ñn]anza Universitaria|"
        r"Ense[ñn]anza Universitaria de la Inform",
        re.IGNORECASE,
    )

    def __init__(self, articles: list[dict], min_title_chars: int = 25) -> None:
        self._titles = [
            (self.normalize(a["titulo"]), a["archivo"].removesuffix(".pdf"), int(a["anio"]))
            for a in articles
        ]
        self._titles = [t for t in self._titles if len(t[0]) >= min_title_chars]

    @staticmethod
    def normalize(text: str) -> str:
        text = unicodedata.normalize("NFKD", text or "")
        text = "".join(c for c in text if not unicodedata.combining(c)).lower()
        return re.sub(r"[^a-z0-9]+", "", text)

    def match(self, reference: str, citing_year: int) -> tuple[bool, str]:
        """``(cita_jenui, id_citado)``; el id va vacío si no se identifica."""
        norm = self.normalize(reference)
        candidates = [
            (len(title), art_id) for title, art_id, year in self._titles
            if year <= citing_year and title in norm
        ]
        if candidates:
            return True, max(candidates)[1]
        return bool(self._VENUE.search(reference)), ""
