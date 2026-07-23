"""Extracción de texto y metadatos desde el PDF."""
from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from jenui.domain.article import Article
from jenui.ingestion.text_normalizer import TextNormalizer


class PdfExtractor:
    """Extrae texto completo y metadatos de un PDF de las actas.

    Los metadatos que salen de aquí son **el plan B**: si el artículo tiene
    ficha HTML, :class:`~jenui.ingestion.ficha_parser.FichaParser` los
    sobrescribe con los suyos, que son fiables. El texto completo, en cambio,
    solo se puede obtener aquí.
    """

    def extract(self, path: Path) -> Article:
        document = fitz.open(path)
        try:
            first_page = TextNormalizer.clean(document[0].get_text())
            full_text = TextNormalizer.clean(
                "\n".join(page.get_text() for page in document)
            )
            title = self._extract_title(document[0])
        finally:
            document.close()

        return Article(
            id=path.stem,
            filename=path.name,
            year=self._extract_year(path.stem),
            title=title,
            authors=self._extract_authors(first_page, title),
            abstract=self._extract_section(
                first_page, ["resumen"],
                ["palabras clave", "palabras-clave", "abstract"],
            ),
            keywords=self._extract_section(
                first_page, ["palabras clave", "palabras-clave"],
                ["abstract", "1.", "1 ", "introducción", "introduccion"],
            ),
            text=full_text,
        )

    # ------------------------------------------------------------- heurísticas
    @staticmethod
    def _extract_year(stem: str) -> int | None:
        match = re.search(r"(20\d{2})", stem)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_title(page) -> str:
        """El título es el texto con mayor tamaño de fuente de la primera página."""
        spans = [
            (round(span["size"], 1), span["bbox"][1], span["text"].strip())
            for block in page.get_text("dict").get("blocks", [])
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if span["text"].strip()
        ]
        if not spans:
            return ""
        max_size = max(size for size, _, _ in spans)
        title_spans = sorted(
            (s for s in spans if s[0] >= max_size - 0.5), key=lambda s: s[1]
        )
        title = " ".join(text for _, _, text in title_spans)
        return TextNormalizer.fix_accents(TextNormalizer.collapse(title))

    @staticmethod
    def _extract_section(text: str, start_labels, end_labels) -> str:
        """Texto entre una etiqueta de inicio y la primera de fin que aparezca."""
        lower = text.lower()
        start = -1
        for label in start_labels:
            match = re.search(rf"\b{re.escape(label)}\b\s*[:\.]?", lower)
            if match:
                start = match.end()
                break
        if start == -1:
            return ""
        end = len(text)
        for label in end_labels:
            match = re.search(rf"\b{re.escape(label)}\b\s*[:\.]?", lower[start:])
            if match:
                end = start + match.start()
                break
        return TextNormalizer.clean(text[start:end])

    @staticmethod
    def _extract_authors(first_page: str, title: str) -> str:
        """Líneas entre el título y 'Resumen': nombres y afiliaciones."""
        if not title:
            return ""
        index = first_page.lower().find("resumen")
        head = first_page[:index] if index != -1 else first_page[:600]
        head = head.replace(title, "", 1).strip()
        lines = [line.strip() for line in head.split("\n") if line.strip()]
        return " | ".join(lines[:6])
