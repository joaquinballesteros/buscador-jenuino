"""Escritura de los resultados del análisis: JSON, CSV e informe HTML."""
from __future__ import annotations

import csv
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("report_template.html")


class ReportWriter:
    """Vuelca el resultado de :class:`TopicAnalysis` en ``data/analysis/``.

    * ``evolucion.json`` — todo, para análisis propios (pandas, R…).
    * ``topics.csv`` — un topic por fila con su clase y métricas.
    * ``topics_por_anio.csv`` — serie de cada topic, en formato largo.
    * ``emergentes_por_anio.csv`` — conceptos por año de aparición.
    * ``conceptos_por_anio.csv`` — artículos por concepto y año.
    * ``informe_topics.html`` — informe autocontenido con las gráficas
      (las gráficas cargan Plotly de jsDelivr; las tablas funcionan sin red).
    """

    def __init__(self, out_dir: Path) -> None:
        self._out = out_dir

    def write(self, result: dict) -> list[Path]:
        self._out.mkdir(parents=True, exist_ok=True)
        written = [
            self._json(result),
            self._topics_csv(result),
            self._series_csv(result),
            self._emerging_csv(result),
            self._concepts_csv(result),
            self._html(result),
        ]
        return written

    # ------------------------------------------------------------------ ficheros
    def _json(self, result: dict) -> Path:
        path = self._out / "evolucion.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def _topics_csv(self, result: dict) -> Path:
        rows = []
        for t in result["topics"]:
            citas = t.get("citas") or {}
            rows.append({
                "id": t["id"], "topic": t["label"], "clase": t["clase"],
                "tendencia": t["tendencia"], "articulos": t["n_articulos"],
                "anio_primero": t["anio_primero"], "anio_inicio": t["anio_inicio"],
                "anio_pico": t["anio_pico"], "pico_pct": round(100 * t["pico"], 2),
                "nivel_reciente": round(t["nivel_reciente"], 3),
                "cobertura": round(t["cobertura"], 3),
                "largo_recorrido": t["largo_recorrido"],
                "citas_internas": citas.get("citas_internas", ""),
                "fraccion_citan_pioneros": self._round(citas.get("fraccion_citan_pioneros")),
                "conceptos": "; ".join(t["conceptos"]),
            })
        return self._csv("topics.csv", rows)

    def _series_csv(self, result: dict) -> Path:
        rows = []
        for t in result["topics"]:
            serie = t["serie"]
            for year, count, share, smooth in zip(serie["years"], serie["counts"],
                                                  serie["share"], serie["smooth"]):
                rows.append({"id": t["id"], "topic": t["label"], "clase": t["clase"],
                             "anio": year, "articulos": count,
                             "prevalencia": round(share, 4),
                             "prevalencia_suavizada": round(smooth, 4)})
        return self._csv("topics_por_anio.csv", rows)

    def _emerging_csv(self, result: dict) -> Path:
        rows = [{
            "anio": e["anio"], "concepto": e["label"], "estado": e["estado"],
            "articulos": e["articulos"], "articulos_despues": e["articulos_despues"],
            "anios_presente_despues": e["anios_presente_despues"],
            "anios_despues": e["anios_despues"],
            "pioneros": " | ".join(f"{p['id']}: {p['titulo']}" for p in e["pioneros"]),
        } for e in result["emergentes"]]
        return self._csv("emergentes_por_anio.csv", rows)

    def _concepts_csv(self, result: dict) -> Path:
        years = result["meta"]["anios"]
        rows = [{"concepto": c["concepto"], "articulos": c["articulos"],
                 **{str(y): n for y, n in zip(years, c["conteos"])}}
                for c in result["conceptos"]]
        return self._csv("conceptos_por_anio.csv", rows)

    def _html(self, result: dict) -> Path:
        path = self._out / "informe_topics.html"
        data = json.dumps(result, ensure_ascii=False).replace("</", "<\\/")
        path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATOS__", data),
                        encoding="utf-8")
        return path

    # ------------------------------------------------------------------ interno
    def _csv(self, name: str, rows: list[dict]) -> Path:
        path = self._out / name
        with open(path, "w", encoding="utf-8", newline="") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        return path

    @staticmethod
    def _round(value):
        return "" if value is None else round(value, 3)
