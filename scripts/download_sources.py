#!/usr/bin/env python3
"""Descarga los PDFs y fichas oficiales de JENUI (aenui.org) a pdf/ y fichas/.

Es el primer paso del proceso, antes de ingest.py: pdf/ y fichas/ no se
versionan (son actas con copyright de JENUI/los autores), así que se traen
desde la web oficial a partir de fuentes/enlaces_jenui.csv (sí versionado).

Incremental: salta los ficheros que ya existen. Ejecutar desde la raíz:

    python scripts/download_sources.py            # descarga lo que falte
    python scripts/download_sources.py --limit 5  # prueba con 5 artículos
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import csv
import ssl
import time
import urllib.error
import urllib.request

import certifi

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "fuentes" / "enlaces_jenui.csv"
USER_AGENT = "buscador-jenui/1.0 (+https://aenui.org)"

# El Python del sistema en macOS no siempre trae un almacén de certificados
# CA usable (da CERTIFICATE_VERIFY_FAILED con cualquier HTTPS). certifi trae
# su propio bundle, así que funciona sin depender de cómo esté configurado
# el Python de cada máquina.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def download(url: str, dest: Path) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT) as response, \
                dest.open("wb") as f:
            f.write(response.read())
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"    [ERROR] {url}: {exc}")
        dest.unlink(missing_ok=True)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descarga PDFs y fichas oficiales de JENUI (aenui.org)."
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="descarga como mucho N artículos nuevos")
    args = parser.parse_args()

    if not CSV_FILE.exists():
        raise SystemExit(f"No existe {CSV_FILE}.")

    pdf_dir = ROOT / "pdf"
    fichas_dir = ROOT / "fichas"
    pdf_dir.mkdir(exist_ok=True)
    fichas_dir.mkdir(exist_ok=True)

    with CSV_FILE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    def falta(row: dict) -> bool:
        ficha = row["archivo"].replace(".pdf", ".html")
        return not (pdf_dir / row["archivo"]).exists() or not (fichas_dir / ficha).exists()

    pending = [r for r in rows if falta(r)]
    if args.limit:
        pending = pending[:args.limit]

    print(f"Artículos: {len(rows)}  |  ya descargados: {len(rows) - len(pending)}  "
          f"|  pendientes: {len(pending)}")
    if not pending:
        print("Nada nuevo que descargar.")
        return

    ok = 0
    for i, row in enumerate(pending, 1):
        archivo = row["archivo"]
        ficha = archivo.replace(".pdf", ".html")
        pdf_ok = (pdf_dir / archivo).exists() or download(row["url_pdf"], pdf_dir / archivo)
        ficha_ok = (fichas_dir / ficha).exists() or download(row["url_ficha"], fichas_dir / ficha)
        estado = "" if pdf_ok and ficha_ok else "  (con errores, relanza el script para reintentar)"
        print(f"  [{i}/{len(pending)}] {archivo}{estado}")
        if pdf_ok and ficha_ok:
            ok += 1
        time.sleep(0.2)   # no martillear el servidor de aenui.org

    print(f"\nDescargados {ok}/{len(pending)} artículos nuevos.")


if __name__ == "__main__":
    main()
