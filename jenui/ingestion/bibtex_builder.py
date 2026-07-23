"""Generación de BibTeX para artículos sin ficha."""
from __future__ import annotations

import re
import unicodedata

from jenui.domain.article import Article


class BibtexBuilder:
    """Construye un BibTeX mínimo a partir de los datos del PDF.

    Solo se usa como red de seguridad para los artículos que no tienen ficha
    HTML: así **todos** los resultados de búsqueda ofrecen una cita, aunque la
    de estos casos sea menos precisa.
    """

    #: Volumen de las actas por año de celebración.
    VOLUMES = {2021: 6, 2022: 7, 2023: 8, 2024: 9, 2025: 10}

    def build(self, article: Article) -> tuple[str, str]:
        """Devuelve ``(bibtex, cite_key)``."""
        key = self._cite_key(article)
        volume = self.VOLUMES.get(article.year, "")
        authors = (article.authors or "").replace(" | ", "; ")
        bibtex = (
            f"@inproceedings{{{key},\n"
            f'\tAUTHOR = "{authors}",\n'
            f'\tTITLE = "{article.title}",\n'
            f'\tBOOKTITLE = "Actas de las JENUI - Vol. {volume} ({article.year})",\n'
            f"\tYEAR = {article.year},\n"
            f"}}"
        )
        return bibtex, key

    @staticmethod
    def _cite_key(article: Article) -> str:
        first = (article.authors or "").split("|")[0].split(",")[0].strip()
        surname = first.split()[-1] if first else ""
        ascii_surname = "".join(
            c for c in unicodedata.normalize("NFKD", surname)
            if not unicodedata.combining(c)
        )
        ascii_surname = re.sub(r"[^A-Za-z]", "", ascii_surname).lower() or "jenui"
        return f"{ascii_surname}{article.year or ''}"
