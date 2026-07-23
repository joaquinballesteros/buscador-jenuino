"""Aplicación web: API de búsqueda e interfaz."""
from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from jenui.config.settings import Settings
from jenui.search.searcher import Searcher


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea la aplicación FastAPI.

    Se usa una fábrica en lugar de una instancia global para poder levantar la
    app con otra configuración en pruebas.

    El buscador se construye una sola vez al arrancar y se mantiene vivo: carga
    el corpus, el índice y el grafo en memoria, y los refresca solo cuando sus
    ficheros cambian.
    """
    settings = settings or Settings.load()
    searcher = Searcher(settings)
    app = FastAPI(title="Buscador JENUINO (GraphRAG local)")

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=2), k: int | None = None,
               corregir: bool = True):
        """Artículos relacionados con la consulta, cada uno con su BibTeX.

        ``corregir=false`` busca el texto tal cual, sin corrección ortográfica.
        """
        return JSONResponse(searcher.search(q, top_k=k, spellcheck=corregir))

    @app.get("/api/explain")
    def explain(q: str = Query(..., min_length=2), k: int | None = None):
        """Búsqueda instrumentada: devuelve las etapas intermedias (recuperador
        vectorial, grafo y ranker). La consume la página /testing."""
        return JSONResponse(searcher.explain(q, top_k=k))

    @app.get("/testing")
    def testing():
        """Página de depuración que muestra los pasos intermedios de la búsqueda."""
        return FileResponse(settings.paths.static_dir / "testing.html")

    @app.get("/api/status")
    def status():
        """Estado del índice: artículos, fragmentos, grafo y proveedores."""
        return searcher.status()

    @app.post("/api/reload")
    def reload():
        """Recarga corpus, índice y grafo. Útil tras añadir artículos."""
        searcher.refresh()
        return searcher.status()

    @app.get("/pdf/{filename}")
    def pdf(filename: str):
        """Sirve el PDF original. Valida el nombre para no salir del directorio."""
        path = (settings.paths.pdf_dir / filename).resolve()
        if (not str(path).startswith(str(settings.paths.pdf_dir.resolve()))
                or not path.exists() or path.suffix.lower() != ".pdf"):
            return JSONResponse({"error": "no encontrado"}, status_code=404)
        return FileResponse(path, media_type="application/pdf")

    app.mount(
        "/",
        StaticFiles(directory=str(settings.paths.static_dir), html=True),
        name="static",
    )
    return app
