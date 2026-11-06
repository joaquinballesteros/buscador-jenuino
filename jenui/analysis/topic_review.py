"""Revisión manual de los topics: Louvain propone, el investigador decide."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from jenui.analysis.concept_source import ConceptCorpus
from jenui.analysis.topic_detector import Topic, TopicDetector
from jenui.graph.alias_resolver import AliasResolver

#: Valores de la columna ``topic`` de conceptos.csv que dejan el concepto fuera.
NO_TOPIC = {"", "-"}
#: Valores que marcan ``descartar`` en topics.csv.
YES = {"x", "si", "sí", "s", "1", "true", "yes"}

TOPIC_COLUMNS = ["topic", "etiqueta_automatica", "articulos", "clase",
                 "nombre", "grupo", "fusionar_en", "descartar", "notas"]
CONCEPT_COLUMNS = ["topic", "concepto", "articulos"]


@dataclass
class ReviewSummary:
    """Cuánto cambia la revisión la detección automática (para el método del artículo)."""

    topics_detectados: int = 0
    topics_finales: int = 0
    fusionados: int = 0
    descartados: int = 0
    nuevos: int = 0
    con_nombre: int = 0
    conceptos_movidos: int = 0
    conceptos_quitados: int = 0
    conceptos_anadidos: int = 0
    #: nombres de conceptos.csv que no están en el corpus (erratas, o cambió el grafo)
    conceptos_desconocidos: list[str] = field(default_factory=list)
    #: conceptos que la detección pone en un topic y la revisión no menciona
    conceptos_sin_revisar: int = 0
    #: topics que se quedan sin artículos tras la revisión
    topics_vacios: list[str] = field(default_factory=list)


class TopicReview:
    """Aplica la revisión manual guardada en ``revision_topics/``.

    Dos CSV que se editan con cualquier hoja de cálculo:

    * ``conceptos.csv`` — un concepto por fila con el topic al que pertenece.
      Cambiar el topic **mueve** el concepto; dejarlo vacío (o ``-``) lo
      **quita** de todos; un identificador nuevo **crea** un topic (para
      dividir uno). Duplicar una fila pone el concepto en dos topics.
    * ``topics.csv`` — un topic por fila: ``nombre`` (la etiqueta del
      artículo), ``grupo`` (familia temática), ``fusionar_en`` (otro topic) y
      ``descartar``.

    La revisión fija los conceptos de cada topic, así que no depende de la
    numeración de la detección: sigue valiendo aunque cambien los parámetros
    de Louvain. Los topics revisados se reconstruyen igual que los detectados
    (:meth:`TopicDetector.topics_from_groups`) y el resto del análisis
    (series, clases, citas, flujo) se calcula sobre ellos.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.topics_file = folder / "topics.csv"
        self.concepts_file = folder / "conceptos.csv"

    def exists(self) -> bool:
        return self.concepts_file.exists()

    # ------------------------------------------------------------------ plantilla
    def write_template(self, topics: list[Topic], corpus: ConceptCorpus,
                       classes: dict[str, str], min_df: int) -> list[Path]:
        """Plantilla con la detección automática, para empezar a revisar."""
        if self.exists():
            raise SystemExit(f"Ya hay una revisión en {self.folder}. Muévela o bórrala "
                             "si de verdad quieres empezar de cero.")
        df = {c: len(a) for c, a in corpus.concept_articles().items()}
        ordered = sorted(topics, key=lambda t: t.id)
        topic_rows = [{"topic": t.id, "etiqueta_automatica": t.label,
                       "articulos": len(t.articles), "clase": classes.get(t.id, "")}
                      for t in ordered]
        concept_rows = [{"topic": t.id, "concepto": corpus.label(c), "articulos": df.get(c, 0)}
                        for t in ordered for c in t.concepts]
        # al final, los conceptos frecuentes que no han caído en ningún topic
        assigned = {c for t in topics for c in t.concepts}
        loose = sorted((c for c, n in df.items() if n >= min_df and c not in assigned),
                       key=lambda c: (-df[c], corpus.label(c)))
        concept_rows += [{"topic": "", "concepto": corpus.label(c), "articulos": df[c]}
                         for c in loose]
        self.folder.mkdir(parents=True, exist_ok=True)
        self._write(self.topics_file, TOPIC_COLUMNS, topic_rows)
        self._write(self.concepts_file, CONCEPT_COLUMNS, concept_rows)
        return [self.topics_file, self.concepts_file]

    # ------------------------------------------------------------------ aplicar
    def apply(self, detected: list[Topic], corpus: ConceptCorpus,
              detector: TopicDetector) -> tuple[list[Topic], ReviewSummary]:
        summary = ReviewSummary(topics_detectados=len(detected))
        before = defaultdict(set)
        for topic in detected:
            for concept in topic.concepts:
                before[concept].add(topic.id)

        index = self._concept_index(corpus)
        assignment: dict[str, set[str]] = defaultdict(set)
        mentioned: set[str] = set()
        for row in self._read(self.concepts_file):
            name = (row.get("concepto") or "").strip()
            if not name:
                continue
            key = index.get(name) or index.get(AliasResolver.normalize(name))
            if key is None:
                summary.conceptos_desconocidos.append(name)
                continue
            mentioned.add(key)
            topic_id = (row.get("topic") or "").strip()
            if topic_id not in NO_TOPIC:
                assignment[key].add(topic_id)

        meta = {(row.get("topic") or "").strip(): row for row in self._read(self.topics_file)}
        meta.pop("", None)
        known = {t for ids in assignment.values() for t in ids}
        final = self._resolver(meta, known)

        groups: dict[str, set[str]] = defaultdict(set)
        for concept, ids in assignment.items():
            for topic_id in ids:
                target = final(topic_id)
                if target:
                    groups[target].add(concept)

        topics = detector.topics_from_groups(corpus, groups)
        for topic in topics:
            row = meta.get(topic.id, {})
            topic.name = (row.get("nombre") or "").strip()
            topic.group = (row.get("grupo") or "").strip()

        detected_ids = {t.id for t in detected}
        summary.topics_finales = len(topics)
        summary.fusionados = sum(1 for t, r in meta.items() if t in known
                                 and (r.get("fusionar_en") or "").strip() not in ("", t))
        summary.descartados = sum(1 for t, r in meta.items() if t in known
                                  and (r.get("descartar") or "").strip().lower() in YES)
        summary.nuevos = len({t.id for t in topics} - detected_ids)
        summary.con_nombre = sum(1 for t in topics if t.name)
        summary.topics_vacios = sorted(set(groups) - {t.id for t in topics})
        for concept in mentioned:
            was, now = before.get(concept, set()), assignment.get(concept, set())
            if was and not now:
                summary.conceptos_quitados += 1
            elif now and not was:
                summary.conceptos_anadidos += 1
            elif was != now:
                summary.conceptos_movidos += 1
        summary.conceptos_sin_revisar = len(set(before) - mentioned)
        return topics, summary

    @staticmethod
    def _resolver(meta: dict[str, dict], known: set[str]):
        """Topic final de cada topic de la revisión: sigue las fusiones; None si se descarta."""
        for topic_id, row in meta.items():
            target = (row.get("fusionar_en") or "").strip()
            if target and target not in known and target not in meta:
                raise SystemExit(f"revision_topics/topics.csv: {topic_id} se fusiona en "
                                 f"{target}, que no existe.")

        def final(topic_id: str, seen: tuple = ()) -> str | None:
            row = meta.get(topic_id, {})
            if (row.get("descartar") or "").strip().lower() in YES:
                return None
            target = (row.get("fusionar_en") or "").strip()
            if not target or target == topic_id:
                return topic_id
            if target in seen:
                raise SystemExit("revision_topics/topics.csv: fusión circular: "
                                 + " → ".join(seen + (topic_id, target)))
            return final(target, seen + (topic_id,))

        return final

    @staticmethod
    def _concept_index(corpus: ConceptCorpus) -> dict[str, str]:
        """Nombre (tal cual o normalizado) → clave del concepto."""
        index: dict[str, str] = {}
        for key in sorted(corpus.labels):
            label = corpus.label(key)
            index.setdefault(key, key)
            index.setdefault(AliasResolver.normalize(label), key)
        for key in sorted(corpus.labels):
            index[corpus.label(key)] = key
        return index

    # ------------------------------------------------------------------ CSV
    @staticmethod
    def _read(path: Path) -> list[dict]:
        """Admite coma, punto y coma o tabulador (Excel en español guarda con ';')."""
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(io.StringIO(text), dialect=dialect))

    @staticmethod
    def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
