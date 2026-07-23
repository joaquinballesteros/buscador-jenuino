"""Reparación del texto extraído de PDFs."""
from __future__ import annotations

import re


class TextNormalizer:
    """Repara los artefactos de codificación típicos de PDFs generados con LaTeX.

    Al extraer texto de estos PDFs, el acento aparece como carácter suelto,
    separado de su vocal, y la eñe como ``n`` seguida de tilde::

        'evaluacio´n'   -> 'evaluación'
        'ensen~anza'    -> 'enseñanza'
        'esta´'         -> 'está'
        'lingu¨´istica' -> 'lingüística'

    El acento puede ir **antes o después** de la vocal según el PDF, así que se
    contemplan ambos órdenes.
    """

    _ACUTE = {
        "a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú",
        "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú",
    }

    @classmethod
    def fix_accents(cls, text: str) -> str:
        """Recompone acentos, diéresis y eñes partidos por la extracción."""
        if not text:
            return text
        # eñe: ~ (U+007E o U+02DC) pegada a una n
        text = re.sub(r"n[~˜]|[~˜]n", "ñ", text)
        text = re.sub(r"N[~˜]|[~˜]N", "Ñ", text)
        # diéresis
        text = re.sub(r"u¨|¨u", "ü", text)
        text = re.sub(r"U¨|¨U", "Ü", text)
        # tilde aguda (U+00B4 o U+02CA) a cualquier lado de la vocal
        text = re.sub(r"([aeiouAEIOU])[´ˊ]", lambda m: cls._ACUTE[m.group(1)], text)
        text = re.sub(r"[´ˊ]([aeiouAEIOU])", lambda m: cls._ACUTE[m.group(1)], text)
        return text.replace("­", "")   # guion suave de partición

    @classmethod
    def clean(cls, text: str) -> str:
        """Limpieza completa: acentos, guiones de corte y espaciado."""
        text = text.replace("­", "")
        text = re.sub(r"-\n(?=\w)", "", text)      # une palabra partida al saltar línea
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return cls.fix_accents(text.strip())

    @staticmethod
    def collapse(text: str) -> str:
        """Colapsa todo el espaciado en una sola línea."""
        return re.sub(r"\s+", " ", text or "").strip()
