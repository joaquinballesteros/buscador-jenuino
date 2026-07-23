"""Persistencia del corpus."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from jenui.domain.article import Article


class CorpusRepository:
    """Lee y escribe el corpus en JSON Lines.

    Un artículo por línea permite **añadir** sin reescribir el fichero, que es
    lo que hace barato incorporar artículos nuevos.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def mtime(self) -> float:
        return self._path.stat().st_mtime if self._path.exists() else 0.0

    # ------------------------------------------------------------------ lectura
    def iter_articles(self) -> Iterator[Article]:
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield Article.from_dict(json.loads(line))

    def load_all(self) -> list[Article]:
        return list(self.iter_articles())

    def load_by_id(self) -> dict[str, Article]:
        return {article.id: article for article in self.iter_articles()}

    def existing_ids(self) -> set[str]:
        """IDs ya presentes. Es la base del comportamiento incremental."""
        if not self._path.exists():
            return set()
        ids = set()
        with open(self._path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    ids.add(json.loads(line)["id"])
        return ids

    # ----------------------------------------------------------------- escritura
    def append(self, articles: list[Article]) -> None:
        self._write(articles, mode="a")

    def replace(self, articles: list[Article]) -> None:
        self._write(articles, mode="w")

    def truncate(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")

    def _write(self, articles: list[Article], mode: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, mode, encoding="utf-8") as handle:
            for article in articles:
                handle.write(json.dumps(article.to_dict(), ensure_ascii=False) + "\n")
