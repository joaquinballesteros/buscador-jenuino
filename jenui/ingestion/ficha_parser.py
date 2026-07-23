"""Lectura de las fichas HTML del congreso."""
from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

from jenui.ingestion.text_normalizer import TextNormalizer

MAX_ABSTRACT_CHARS = 1500


class FichaParser:
    """Extrae metadatos y BibTeX de la ficha HTML de un artículo.

    Las fichas son la fuente **fiable** de título, autores y BibTeX: salen de
    una base de datos estructurada, con los acentos correctos. El PDF, en
    cambio, arrastra artefactos de extracción e incluso desordena el título.

    Salvedad importante: el bloque de resumen de las fichas de los últimos años
    sí arrastra los artefactos del PDF, de modo que también se pasa por
    :class:`TextNormalizer`.
    """

    def __init__(self, fichas_dir: Path) -> None:
        self._dir = fichas_dir

    def parse(self, article_id: str) -> dict | None:
        """Devuelve los campos de la ficha, o ``None`` si no existe."""
        path = self._dir / f"{article_id}.html"
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8", errors="replace")

        fields: dict = {}
        self._add_title(raw, fields)
        self._add_authors(raw, fields)
        self._add_summary_block(raw, fields)
        self._add_category(raw, fields)
        self._add_venue(raw, fields)
        self._add_bibtex(raw, fields)
        return fields

    # ------------------------------------------------------------ extractores
    def _add_title(self, raw: str, fields: dict) -> None:
        match = re.search(r'class="tituloFicha"[^>]*>(.*?)(?:<span|</div>)', raw, re.S)
        if match:
            fields["title"] = TextNormalizer.fix_accents(self._strip_tags(match.group(1)))

    def _add_authors(self, raw: str, fields: dict) -> None:
        match = re.search(r'class="autoresFicha"[^>]*>(.*?)</div>', raw, re.S)
        if match:
            fields["authors"] = TextNormalizer.fix_accents(self._strip_tags(match.group(1)))

    def _add_summary_block(self, raw: str, fields: dict) -> None:
        """El bloque trae: resumen ES, 'Abstract' EN y 'Palabras clave'."""
        match = re.search(r'class="resumenFicha"[^>]*>(.*?)</div>', raw, re.S)
        if not match:
            return
        block = self._block_to_text(match.group(1))
        spanish = re.split(
            r"\n(?:Abstract|Palabras clave|Keywords)\b", block, maxsplit=1, flags=re.I
        )[0]
        fields["abstract"] = TextNormalizer.fix_accents(spanish).strip()[:MAX_ABSTRACT_CHARS]
        keywords = self._extract_keywords(block)
        if keywords:
            fields["keywords"] = keywords

    # el título de sección que suele seguir a las palabras clave (num. árabe o romano)
    _SECTION_AFTER_KW = re.compile(
        r"\s+(?:I{1,3}\.|IV\.|V\.|1\.|2\.|Abstract|Keywords|Introducci[oó]n)\b", re.I
    )
    _MAX_KEYWORDS_CHARS = 250

    def _extract_keywords(self, block: str) -> str:
        """Palabras clave tras el encabezado, sea cual sea el separador.

        Tolera 'Palabras clave: kw', 'Palabras clave--kw' y 'Palabras clave\\nkw'.
        Se queda con una sola línea y corta si se cuela el inicio de una sección
        (p. ej. 'I. INTRODUCCIÓN'), que es justo lo que antes se colaba entero.
        """
        match = re.search(r"Palabras\s+clave\s*[:\-–—]*\s*(.+)", block, re.I)
        if not match:
            return ""
        text = match.group(1)                      # una sola línea (. no cruza \n)
        text = self._SECTION_AFTER_KW.split(text, maxsplit=1)[0]
        text = TextNormalizer.fix_accents(text).strip(" -–—:;,\t")
        return text[:self._MAX_KEYWORDS_CHARS]

    def _add_category(self, raw: str, fields: dict) -> None:
        # el HTML usa la entidad &iacute;, no el carácter
        match = re.search(r"Categor(?:[ií]|&iacute;)a:\s*(.*?)<br", raw, re.S | re.I)
        if match:
            fields["category"] = TextNormalizer.fix_accents(self._strip_tags(match.group(1)))

    def _add_venue(self, raw: str, fields: dict) -> None:
        match = re.search(r'class="datosCongresoFicha"[^>]*>(.*?)</div>', raw, re.S)
        if match:
            fields["venue"] = self._strip_tags(match.group(1))

    def _add_bibtex(self, raw: str, fields: dict) -> None:
        """El BibTeX de la ficha trae la clave literal 'key' en todos los
        artículos, lo que la hace inservible para citar. Se sustituye por
        ``apellidoAño``."""
        match = re.search(r"bibtexFicha.*?<pre>(.*?)</pre>", raw, re.S)
        if not match:
            return
        bibtex = html.unescape(match.group(1)).strip()
        authors = re.search(r'AUTHOR\s*=\s*"([^"]*)"', bibtex)
        year = re.search(r"YEAR\s*=\s*(\d{4})", bibtex)
        if authors:
            key = self.build_cite_key(authors.group(1), year.group(1) if year else "")
            bibtex = re.sub(r"@(\w+)\{[^,]*,", rf"@\1{{{key},", bibtex, count=1)
            fields["cite_key"] = key
        fields["bibtex"] = bibtex

    # --------------------------------------------------------------- utilidades
    @staticmethod
    def build_cite_key(author_field: str, year) -> str:
        """``'Martínez Prieto,Miguel A.;...'`` + 2021 -> ``martinezprieto2021``."""
        surname = author_field.split(";")[0].split(",")[0]
        ascii_surname = "".join(
            c for c in unicodedata.normalize("NFKD", surname)
            if not unicodedata.combining(c)
        )
        ascii_surname = re.sub(r"[^A-Za-z]", "", ascii_surname).lower()
        return f"{ascii_surname or 'jenui'}{year or ''}"

    @staticmethod
    def _strip_tags(fragment: str) -> str:
        return TextNormalizer.collapse(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))

    @staticmethod
    def _block_to_text(fragment: str) -> str:
        """Convierte un fragmento con ``<br/>`` en texto con saltos de línea."""
        text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        return "\n".join(line for line in lines if line)
