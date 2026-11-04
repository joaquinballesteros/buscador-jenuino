"""Orquestación de la ingesta."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from jenui.config.settings import Settings
from jenui.domain.article import Article
from jenui.ingestion.bibliography_stripper import BibliographyStripper
from jenui.ingestion.bibtex_builder import BibtexBuilder
from jenui.ingestion.corpus_repository import CorpusRepository
from jenui.ingestion.ficha_parser import FichaParser
from jenui.ingestion.pdf_extractor import PdfExtractor
from jenui.ingestion.text_quality import TextQuality


@dataclass
class IngestReport:
    """Resultado de una ingesta."""

    total_pdfs: int
    already_indexed: int
    processed: int
    failed: list[str]
    repaired: int = 0

    @property
    def pending(self) -> int:
        return self.total_pdfs - self.already_indexed


class CorpusBuilder:
    """Construye el corpus a partir de los PDFs y sus fichas.

    Es **incremental** por defecto: solo procesa los PDFs cuyo identificador no
    está ya en el corpus, de modo que añadir un año nuevo cuesta lo que cuesten
    esos artículos y no los 254 anteriores.

    Para cada artículo combina dos fuentes, por orden de fiabilidad:

    1. el PDF, que aporta el texto completo y unos metadatos aproximados;
    2. la ficha HTML, que sobrescribe título, autores, resumen y BibTeX.

    Al final se reparan los textos ilegibles por fuentes mal codificadas (ver
    :class:`~jenui.ingestion.text_quality.TextQuality`). Este paso necesita el
    vocabulario de todo el corpus, por eso va después de extraer y no dentro
    de cada artículo.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._paths = settings.paths
        self._extractor = PdfExtractor()
        self._fichas = FichaParser(settings.paths.fichas_dir)
        self._bibtex = BibtexBuilder()
        self._repository = CorpusRepository(settings.paths.corpus_file)
        self._strip_bibliography = settings.get(
            "ingestion.quitar_bibliografia", True
        )
        self._bibliography = BibliographyStripper()
        self._excluded = set(settings.get("ingestion.excluir", []))
        self._metadata_only = set(settings.get("ingestion.solo_metadatos", []))

    @property
    def repository(self) -> CorpusRepository:
        return self._repository

    def build(self, rebuild: bool = False, limit: int | None = None,
              verbose: bool = True) -> IngestReport:
        pdfs = [p for p in sorted(self._paths.pdf_dir.glob("*.pdf"))
                if p.stem not in self._excluded]
        if not pdfs:
            raise SystemExit(f"No hay PDFs en {self._paths.pdf_dir}")

        done = set() if rebuild else self._repository.existing_ids()
        pending = [p for p in pdfs if p.stem not in done]
        if limit:
            pending = pending[:limit]

        if rebuild:
            self._repository.truncate()

        processed: list[Article] = []
        failed: list[str] = []
        for index, path in enumerate(pending, start=1):
            try:
                article = self._build_article(path)
                processed.append(article)
                if verbose:
                    title = (article.title or "(sin título)")[:60]
                    print(f"[{index:3}/{len(pending)}] {path.name} "
                          f"{article.n_chars:>7} chars  {title}")
            except Exception as exc:  # noqa: BLE001 - un PDF roto no aborta el lote
                failed.append(path.name)
                print(f"[{index:3}/{len(pending)}] ERROR {path.name}: {exc}",
                      file=sys.stderr)

        repaired = 0
        if processed:
            reference = processed if rebuild else self._repository.load_all() + processed
            repaired = self._repair(processed, reference)
            self._repository.append(processed)

        return IngestReport(
            total_pdfs=len(pdfs),
            already_indexed=len(done),
            processed=len(processed),
            failed=failed,
            repaired=repaired,
        )

    def repair_existing(self) -> int:
        """Aplica al corpus ya construido, sin releer los PDFs, la reparación de
        textos ilegibles y las listas ``excluir`` / ``solo_metadatos``."""
        loaded = self._repository.load_all()
        articles = [a for a in loaded if a.id not in self._excluded]
        repaired = len(loaded) - len(articles)
        for article in articles:
            if article.id in self._metadata_only and (article.abstract or article.text):
                article.abstract, article.text = "", ""
                repaired += 1
        repaired += self._repair(articles, articles)
        if repaired:
            self._repository.replace(articles)
        return repaired

    @staticmethod
    def _repair(articles: list[Article], reference: list[Article]) -> int:
        """Sustituye resumen y cuerpo ilegibles por su mejor variante.

        Devuelve cuántos artículos cambian.
        """
        quality = TextQuality.from_articles(reference)
        changed = 0
        for article in articles:
            if not (article.abstract or article.text):
                continue
            abstract = quality.best_abstract(article.abstract, article.text, article.title)
            body = quality.best_body(article.text)
            if abstract != (article.abstract or "") or body != (article.text or ""):
                article.abstract, article.text = abstract, body
                changed += 1
        return changed

    # ------------------------------------------------------------------ interno
    def _build_article(self, path: Path) -> Article:
        article = self._extractor.extract(path)
        self._merge_ficha(article)
        if article.id in self._metadata_only:
            # el PDF oficial es otro documento: nada de lo extraído es del artículo
            article.abstract, article.text = "", ""
        article.keywords = self._clean_keywords(article.keywords)
        if self._strip_bibliography:
            # el cuerpo pierde las referencias; título/resumen/keywords no se tocan
            article.text = self._bibliography.strip(article.text)
        if not article.bibtex:
            article.bibtex, article.cite_key = self._bibtex.build(article)
        return article

    # el inicio de la primera sección tras las palabras clave: "1. Motivación",
    # "I. INTRODUCCIÓN", "Abstract"... — lo que a veces se cuela en el campo.
    _SECTION_START = re.compile(
        r"(?:\b\d{1,2}|\b[IVX]{1,4})\.\s+[A-ZÁÉÍÓÚ]"          # 1. Motivación / I. INTRO
        r"|(?i:\b(?:abstract|keywords)\b)"                    # abstract inglés
        r"|(?i:lugar de publicaci|[ií]ndice de impacto)"       # premios AENUI (revistas)
    )

    @classmethod
    def _clean_keywords(cls, keywords: str) -> str:
        """Deja solo las palabras clave: colapsa saltos y corta si se ha colado
        el arranque de una sección (numeral árabe o romano, o 'Abstract')."""
        if not keywords:
            return ""
        text = re.sub(r"\s+", " ", keywords).strip()
        match = cls._SECTION_START.search(text)
        if match:
            text = text[:match.start()]
        return text.strip(" -–—:;,.\t")[:220]

    def _merge_ficha(self, article: Article) -> None:
        """Sobrescribe con los datos limpios de la ficha, si la hay."""
        ficha = self._fichas.parse(article.id)
        if not ficha:
            return
        for field in ("title", "authors", "category", "venue",
                      "bibtex", "cite_key", "abstract", "keywords"):
            value = ficha.get(field)
            if value:
                setattr(article, field, value)
