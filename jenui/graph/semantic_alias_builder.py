"""Generación del mapa de alias semánticos."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import numpy as np

from jenui.config.settings import Settings
from jenui.graph.alias_resolver import AliasResolver
from jenui.graph.entity_type_filter import EntityTypeFilter
from jenui.graph.graph_reader import GraphReader
from jenui.providers.provider_factory import ProviderFactory


@dataclass
class AliasReport:
    """Resultado de una generación de alias.

    Incluye el propio mapa (``aliases``) para que quien lo pida decida si lo
    guarda o solo lo inspecciona.
    """

    entities: int
    groups_after_text: int
    groups_final: int
    merges: list[tuple[str, str, float]]
    aliases: dict[str, str]
    seconds: float

    @property
    def n_merges(self) -> int:
        return len(self.merges)

    def top_merges(self, limit: int = 25) -> list[tuple[str, str, float]]:
        """Fusiones ordenadas por confianza, para revisarlas."""
        return sorted(self.merges, key=lambda m: -m[2])[:limit]


class SemanticAliasBuilder:
    """Agrupa entidades equivalentes comparando embeddings de sus nombres.

    Es la segunda capa de :class:`~jenui.graph.alias_resolver.AliasResolver`:
    la primera une variantes tipográficas y esta las que ni se parecen
    textualmente (``ABP`` ↔ ``Aprendizaje basado en proyectos``).

    Optimización: primero agrupa por normalización textual y solo embebe **un
    representante por grupo**, así que procesa bastantes menos nombres de los
    que hay entidades.

    Usa solo el modelo de embeddings, nunca el LLM: es local y sin coste.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._paths = settings.paths
        self._embeddings = ProviderFactory(settings).embeddings()
        self._resolver = AliasResolver(None)     # sin mapa previo: lo estamos creando
        self._reader = GraphReader(
            settings.paths.graphml_file,
            settings.paths.chunks_kv_file,
            EntityTypeFilter(settings.search.get("tipos_entidad_descartados")),
        )

    @property
    def default_threshold(self) -> float:
        return float(self._settings.search.get("umbral_alias", 0.92))

    def build(self, threshold: float | None = None, batch_size: int = 32,
              verbose: bool = True) -> "AliasReport":
        if not self._reader.exists():
            raise SystemExit("No hay grafo todavía. Ejecuta build_graph.py primero.")
        threshold = threshold if threshold is not None else self.default_threshold

        raw = self._reader.read()
        counts = {e: len(a) for e, a in raw.entity_to_articles.items()}
        groups = self._group_by_text(counts)
        keys = sorted(groups)
        if verbose:
            print(f"Entidades: {len(counts)}  ->  {len(keys)} tras normalizar texto")
            print(f"Embebiendo nombres con {self._embeddings.name}/"
                  f"{self._embeddings.model}...")

        started = time.time()
        representatives = [groups[k]["name"] for k in keys]
        vectors = self._embed(representatives, batch_size, verbose)
        merges, aliases = self._cluster(keys, groups, vectors, threshold)

        return AliasReport(
            entities=len(counts),
            groups_after_text=len(keys),
            groups_final=len(keys) - len(merges),
            merges=merges,
            aliases=aliases,
            seconds=time.time() - started,
        )

    def save(self, aliases: dict[str, str]) -> None:
        self._paths.aliases_file.parent.mkdir(parents=True, exist_ok=True)
        self._paths.aliases_file.write_text(
            json.dumps(aliases, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ------------------------------------------------------------------ interno
    def _group_by_text(self, counts: dict[str, int]) -> dict[str, dict]:
        """Agrupa por normalización y elige un representante legible."""
        buckets: dict[str, list[tuple[str, int]]] = {}
        for entity, n_articles in counts.items():
            buckets.setdefault(self._resolver.normalize(entity), []).append(
                (entity, n_articles)
            )
        return {
            key: {
                "name": sorted(items, key=lambda t: (-t[1], -len(t[0])))[0][0],
                "weight": sum(n for _, n in items),
            }
            for key, items in buckets.items()
        }

    @property
    def _cache_file(self):
        return self._paths.data_dir / "entity_name_vectors.npz"

    def _load_cache(self) -> dict[str, np.ndarray]:
        """Vectores de nombres ya embebidos en ejecuciones anteriores."""
        if not self._cache_file.exists():
            return {}
        try:
            data = np.load(self._cache_file, allow_pickle=False)
            names = data["names"].tolist()
            if data["vectors"].shape[1] != self._embeddings.dim:
                return {}      # cambió el modelo de embeddings: cache inservible
            return dict(zip(names, data["vectors"]))
        except (OSError, KeyError, ValueError):
            return {}

    def _save_cache(self, cache: dict[str, np.ndarray]) -> None:
        if not cache:
            return
        names = list(cache)
        np.savez_compressed(
            self._cache_file,
            names=np.array(names),
            vectors=np.stack([cache[n] for n in names]),
        )

    def _embed(self, names: list[str], batch_size: int, verbose: bool) -> np.ndarray:
        """Embebe los nombres, reutilizando los ya calculados.

        La caché hace que recalibrar el umbral sea instantáneo: solo se embeben
        los nombres nuevos.
        """
        cache = self._load_cache()
        missing = [n for n in names if n not in cache]
        if verbose and cache:
            print(f"  caché: {len(names) - len(missing)}/{len(names)} ya calculados")

        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            for name, vector in zip(batch, self._embeddings.embed(batch)):
                cache[name] = vector
            if verbose and (start // batch_size) % 20 == 0:
                print(f"  {min(start + batch_size, len(missing))}/{len(missing)}")
        if missing:
            self._save_cache(cache)

        vectors = np.stack([cache[n] for n in names]).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def _cluster(self, keys: list[str], groups: dict[str, dict],
                 vectors: np.ndarray, threshold: float
                 ) -> tuple[list[tuple[str, str, float]], dict[str, str]]:
        """Agrupación voraz: los conceptos más frecuentes actúan de canónicos."""
        order = sorted(range(len(keys)), key=lambda i: -groups[keys[i]]["weight"])
        canonical_indices: list[int] = []
        aliases: dict[str, str] = {}
        merges: list[tuple[str, str, float]] = []

        for index in order:
            if canonical_indices:
                similarities = vectors[canonical_indices] @ vectors[index]
                best = int(np.argmax(similarities))
                if float(similarities[best]) >= threshold:
                    target = keys[canonical_indices[best]]
                    aliases[keys[index]] = target
                    merges.append((
                        groups[keys[index]]["name"],
                        groups[target]["name"],
                        float(similarities[best]),
                    ))
                    continue
            canonical_indices.append(index)
        return merges, aliases
