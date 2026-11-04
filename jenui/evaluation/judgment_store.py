"""Banco de evaluación de la búsqueda: consultas, candidatos y juicios."""
from __future__ import annotations

import csv
import json
import os
import re
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path


class JudgmentStore:
    """Ficheros del banco de evaluación, en ``evaluacion/``.

    * ``consultas.csv`` — las consultas, con su criterio de relevancia (a mano).
    * ``candidatos.json`` — por consulta, los artículos a juzgar: la unión de
      los mejores resultados de varias configuraciones del buscador (*pooling*,
      ver ``scripts/eval_pool.py``), en orden aleatorio para no delatar de qué
      configuración viene cada uno.
    * ``juicios/<evaluador>.csv`` — los juicios de cada persona: 0 no
      relevante, 1 parcialmente relevante, 2 muy relevante.

    Cada evaluador juzga a ciegas y en su propio fichero, así que varias
    personas pueden trabajar a la vez (o en copias distintas del repositorio)
    sin pisarse. El juicio de referencia de cada (consulta, artículo) es la
    **mediana** de los evaluadores (ver :meth:`consensus`).
    """

    SCALE = (0, 1, 2)
    _FIELDS = ["consulta", "articulo", "relevancia", "fecha"]
    _EVALUATOR = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._lock = threading.Lock()

    @property
    def queries_file(self) -> Path:
        return self._dir / "consultas.csv"

    @property
    def candidates_file(self) -> Path:
        return self._dir / "candidatos.json"

    @property
    def judgments_dir(self) -> Path:
        return self._dir / "juicios"

    @classmethod
    def normalize_evaluator(cls, name: str) -> str:
        """Identificador de evaluador apto para nombre de fichero."""
        slug = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
        if not cls._EVALUATOR.match(slug):
            raise ValueError("nombre de evaluador no válido")
        return slug

    # ------------------------------------------------------------------ lectura
    def queries(self) -> list[dict]:
        if not self.queries_file.exists():
            return []
        with open(self.queries_file, encoding="utf-8", newline="") as handle:
            return [{k: (v or "").strip() for k, v in row.items()}
                    for row in csv.DictReader(handle)]

    def query(self, query_id: str) -> dict | None:
        return next((q for q in self.queries() if q["id"] == query_id), None)

    def candidates(self) -> dict[str, list[str]]:
        if not self.candidates_file.exists():
            return {}
        return json.loads(self.candidates_file.read_text(encoding="utf-8"))

    def evaluators(self) -> list[str]:
        if not self.judgments_dir.exists():
            return []
        return sorted(p.stem for p in self.judgments_dir.glob("*.csv"))

    def judgments(self, evaluator: str) -> dict[tuple[str, str], int]:
        """Juicios de un evaluador: ``(consulta, artículo) -> relevancia``."""
        return {key: int(row["relevancia"]) for key, row in self._rows(evaluator).items()}

    def all_judgments(self) -> dict[tuple[str, str], dict[str, int]]:
        """``(consulta, artículo) -> {evaluador: relevancia}``."""
        merged: dict[tuple[str, str], dict[str, int]] = {}
        for evaluator in self.evaluators():
            for key, value in self.judgments(evaluator).items():
                merged.setdefault(key, {})[evaluator] = value
        return merged

    def consensus(self, min_judges: int = 1) -> dict[tuple[str, str], float]:
        """Mediana de los evaluadores por (consulta, artículo).

        Con un número par de juicios la mediana es la media de los dos
        centrales (p. ej. 1,5), que nDCG admite como ganancia graduada.
        """
        return {key: statistics.median(votes.values())
                for key, votes in self.all_judgments().items()
                if len(votes) >= min_judges}

    # ---------------------------------------------------------------- escritura
    def save_candidates(self, pool: dict[str, list[str]]) -> None:
        self._atomic_write(self.candidates_file,
                           json.dumps(pool, ensure_ascii=False, indent=1) + "\n")

    def judge(self, evaluator: str, query_id: str, article_id: str,
              relevance: int | None) -> None:
        """Guarda un juicio del evaluador; ``None`` lo borra."""
        evaluator = self.normalize_evaluator(evaluator)
        if relevance is not None and relevance not in self.SCALE:
            raise ValueError(f"relevancia fuera de escala: {relevance}")
        with self._lock:
            rows = self._rows(evaluator)
            key = (query_id, article_id)
            if relevance is None:
                rows.pop(key, None)
            else:
                rows[key] = {
                    "consulta": query_id, "articulo": article_id,
                    "relevancia": relevance,
                    "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            lines = [",".join(self._FIELDS)]
            for _, row in sorted(rows.items()):
                lines.append(",".join(str(row[f]) for f in self._FIELDS))
            self._atomic_write(self._file(evaluator), "\n".join(lines) + "\n")

    # ------------------------------------------------------------------ interno
    def _file(self, evaluator: str) -> Path:
        return self.judgments_dir / f"{self.normalize_evaluator(evaluator)}.csv"

    def _rows(self, evaluator: str) -> dict[tuple[str, str], dict]:
        path = self._file(evaluator)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8", newline="") as handle:
            return {(r["consulta"], r["articulo"]): r for r in csv.DictReader(handle)}

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
