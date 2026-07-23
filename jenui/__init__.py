"""Buscador JENUI: búsqueda semántica sobre artículos de congreso.

Arquitectura por capas, con dependencias en un solo sentido::

    domain                      modelo puro, sin dependencias
    config                      configuración y rutas
    providers    -> config      estrategias de LLM y embeddings
    ingestion    -> domain      PDFs y fichas  -> corpus
    indexing     -> providers   corpus         -> índice vectorial y grafo
    graph        -> providers   grafo LightRAG -> entidades por artículo
    search       -> todo        consulta       -> artículos relacionados
    web          -> search      API HTTP e interfaz

Ver docs/ARCHITECTURE.md.
"""
__version__ = "1.0.0"
