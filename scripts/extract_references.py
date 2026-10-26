#!/usr/bin/env python3
"""Extrae las referencias bibliográficas de cada artículo a un CSV.

Recorre los PDFs de pdf/ que aparecen en fuentes/enlaces_jenui.csv y escribe
una fila por referencia en fuentes/referencias_jenui.csv. Además marca las
referencias que citan a otro artículo de JENUI y, cuando el título coincide,
el identificador del artículo citado (útil para la red de citas interna).

Columna ``metodo``: "numerada" (partida por [1], [2]…, fiable) o "bloques"
(actas antiguas sin numerar o escaneadas, aproximada).

Ejecutar desde la raíz (necesita los PDFs descargados con download_sources.py):

    python scripts/extract_references.py
    python scripts/extract_references.py --anio 2026
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import csv
import re

from jenui.ingestion.reference_extractor import JenuiCitationMatcher, ReferenceExtractor

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "fuentes" / "enlaces_jenui.csv"
OUT_FILE = ROOT / "fuentes" / "referencias_jenui.csv"
COLUMNS = ["anio", "archivo", "titulo_articulo", "n", "referencia", "anio_referencia",
           "cita_jenui", "jenui_citado", "metodo"]


def reference_year(text: str) -> str:
    """El último año plausible que aparece en la referencia (suele ser el de publicación)."""
    years = re.findall(r"(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)", text)
    return years[-1] if years else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrae las referencias de los artículos a CSV.")
    parser.add_argument("--anio", type=int, nargs="*", help="solo estos años")
    parser.add_argument("--salida", type=Path, default=OUT_FILE)
    args = parser.parse_args()

    with CSV_FILE.open(encoding="utf-8", newline="") as f:
        articles = list(csv.DictReader(f))

    extractor = ReferenceExtractor()
    matcher = JenuiCitationMatcher(articles)
    pdf_dir = ROOT / "pdf"

    selected = [a for a in articles if not args.anio or int(a["anio"]) in args.anio]
    rows, missing, without_refs = [], 0, 0
    for i, art in enumerate(selected, 1):
        path = pdf_dir / art["archivo"]
        if not path.exists():
            missing += 1
            continue
        refs = extractor.extract(path)
        if not refs:
            without_refs += 1
        for ref in refs:
            cita, citado = matcher.match(ref.texto, int(art["anio"]))
            rows.append({
                "anio": art["anio"], "archivo": art["archivo"], "titulo_articulo": art["titulo"],
                "n": ref.numero, "referencia": ref.texto,
                "anio_referencia": reference_year(ref.texto),
                "cita_jenui": "si" if cita else "no", "jenui_citado": citado,
                "metodo": ref.metodo,
            })
        if i % 100 == 0:
            print(f"  {i}/{len(selected)} artículos…")

    with args.salida.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    processed = len(selected) - missing
    print(f"Artículos procesados: {processed}  |  sin PDF local: {missing}  "
          f"|  sin referencias detectadas: {without_refs}")
    print(f"Referencias: {len(rows)}  |  citan JENUI: "
          f"{sum(r['cita_jenui'] == 'si' for r in rows)}  |  con artículo identificado: "
          f"{sum(bool(r['jenui_citado']) for r in rows)}")
    print(f"-> {args.salida.relative_to(ROOT) if args.salida.is_relative_to(ROOT) else args.salida}")


if __name__ == "__main__":
    main()
