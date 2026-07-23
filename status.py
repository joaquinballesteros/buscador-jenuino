#!/usr/bin/env python3
"""Estado del sistema: progreso del grafo, índice vectorial y corpus.

    python status.py             # una foto del estado
    python status.py --watch     # se refresca cada 30 s (Ctrl-C para salir)

Lee el estado real de disco (no un log), así que funciona aunque el proceso se
haya reiniciado y aunque lo lances desde otra terminal.
"""
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone

from jenui.config import Settings
from jenui.graph import KnowledgeGraph
from jenui.indexing import VectorIndex
from jenui.ingestion import CorpusRepository

BAR_WIDTH = 34


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _bar(done: int, total: int) -> str:
    if not total:
        return "-" * BAR_WIDTH
    filled = int(BAR_WIDTH * done / total)
    return "█" * filled + "·" * (BAR_WIDTH - filled)


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def graph_progress(settings: Settings) -> None:
    """Progreso de la construcción del grafo, con ritmo y ETA."""
    status_file = settings.paths.rag_dir / "kv_store_doc_status.json"
    if not status_file.exists():
        print("Grafo:      sin empezar (ejecuta build_graph.py)")
        return

    docs = json.loads(status_file.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for entry in docs.values():
        counts[entry.get("status", "?")] = counts.get(entry.get("status", "?"), 0) + 1

    total = len(docs)
    done = counts.get("processed", 0)
    chunks = sum(e.get("chunks_count", 0) for e in docs.values()
                 if e.get("status") == "processed")

    print(f"Grafo:      [{_bar(done, total)}] {done}/{total} documentos "
          f"({100 * done / total if total else 0:.0f} %)")
    detail = "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    print(f"            {detail}   |   fragmentos procesados: {chunks}")

    remaining = total - done
    if not remaining:
        print("            completo ✓")
        return

    # ritmo y ETA a partir de las marcas de tiempo reales
    stamps = sorted(
        s for s in (_parse(e.get("updated_at")) for e in docs.values()
                    if e.get("status") == "processed") if s
    )
    if len(stamps) >= 2:
        elapsed = (stamps[-1] - stamps[0]).total_seconds()
        if elapsed > 0:
            per_doc = elapsed / (len(stamps) - 1)
            print(f"            ritmo: {3600 / per_doc:.0f} docs/h  "
                  f"({_fmt_duration(per_doc)}/doc)   |   "
                  f"faltan ~{_fmt_duration(remaining * per_doc)}")
            # el aviso solo tiene sentido si aún queda trabajo por hacer
            idle = (datetime.now(timezone.utc) - stamps[-1]).total_seconds()
            if idle > 600:
                print(f"            [!] sin avance desde hace {_fmt_duration(idle)}: "
                      f"revisa si el proceso sigue vivo")


def process_state() -> None:
    """Indica si el proceso de construcción sigue corriendo."""
    result = subprocess.run(["pgrep", "-f", "build_graph.py"],
                            capture_output=True, text=True)
    pids = result.stdout.split()
    print(f"Proceso:    {'CORRIENDO (PID ' + pids[0] + ')' if pids else 'parado'}")


def index_state(settings: Settings) -> None:
    corpus = CorpusRepository(settings.paths.corpus_file)
    n_articles = len(corpus.existing_ids())
    index = VectorIndex.load(settings.paths.vectors_file,
                             settings.paths.vectors_meta_file)
    print(f"Corpus:     {n_articles} artículos")
    print(f"Vectorial:  {'listo' if index.is_ready else 'sin construir'} "
          f"({index.n_chunks} fragmentos, dim {index.dim})")


def graph_state(settings: Settings) -> None:
    graph = KnowledgeGraph(settings)
    if not graph.is_ready:
        print("Conceptos:  aún sin entidades utilizables")
        return
    print(f"Conceptos:  {graph.n_entities} entidades  "
          f"(descartadas {graph.discarded} de metadatos, "
          f"fusionadas {graph.merged} variantes)")
    shared = sum(1 for arts in graph.entity_to_articles.values() if len(arts) >= 2)
    pct = 100 * shared / graph.n_entities if graph.n_entities else 0
    print(f"            conectan 2+ artículos: {shared} ({pct:.0f} %) "
          f"<- las que aportan 'relacionados'")


def show(settings: Settings) -> None:
    print("=" * 62)
    print(f"  Buscador JENUI · {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 62)
    index_state(settings)
    graph_progress(settings)
    graph_state(settings)
    process_state()


def main() -> None:
    parser = argparse.ArgumentParser(description="Estado del sistema.")
    parser.add_argument("--watch", action="store_true",
                        help="refresca cada 30 s")
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()

    settings = Settings.load()
    if not args.watch:
        show(settings)
        return
    try:
        while True:
            print("\033[2J\033[H", end="")   # limpia pantalla
            show(settings)
            print("\n(Ctrl-C para salir)")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
