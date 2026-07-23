"""Eliminación de la sección de bibliografía del texto de un artículo."""
from __future__ import annotations

import re


class BibliographyStripper:
    """Recorta la bibliografía final del texto de un artículo.

    Las referencias son decenas de títulos citados, autores y congresos que, al
    construir el grafo, se convierten en entidades que no describen el contenido
    del artículo ("Does active learning work? A review...") y solo meten ruido.
    Quitarlas en origen es mejor que filtrarlas después.

    Heurística conservadora: busca el encabezado de referencias (``Referencias``,
    ``Bibliografía``, ``References``) y corta desde ahí hasta el final. Para no
    cortar de más, solo actúa si:

    * el encabezado está en la parte final del documento (``min_position``), y
    * lo que se eliminaría no supera una fracción del texto (``max_fraction``).

    Así, un artículo corto sin bibliografía o una mención de "referencias" a
    mitad de texto no disparan el recorte.
    """

    _HEADING = re.compile(
        r"\n[ \t]*(?:\d+\.?\s*)?"
        r"(Referencias(?:\s+bibliogr[aá]ficas)?|Bibliograf[ií]a|References)"
        r"[ \t]*\n",
        re.IGNORECASE,
    )

    def __init__(self, min_position: float = 0.55, max_fraction: float = 0.45) -> None:
        self._min_position = min_position
        self._max_fraction = max_fraction

    def strip(self, text: str) -> str:
        cut = self.find_cut(text)
        return text[:cut].rstrip() if cut is not None else text

    def find_cut(self, text: str) -> int | None:
        """Posición donde empieza la bibliografía, o ``None`` si no procede cortar."""
        if not text:
            return None
        length = len(text)
        # el último encabezado que caiga en la parte final del documento
        candidate = None
        for match in self._HEADING.finditer(text):
            if match.start() >= length * self._min_position:
                candidate = match.start()
        if candidate is None:
            return None
        if (length - candidate) > length * self._max_fraction:
            return None      # eliminaría demasiado: probablemente no es la bibliografía
        return candidate
