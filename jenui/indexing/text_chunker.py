"""Troceado de texto para el índice vectorial."""
from __future__ import annotations

from jenui.domain.article import Article


class TextChunker:
    """Trocea el texto en fragmentos solapados.

    El solape evita que una idea que cae justo en el corte quede mal
    representada en ambos fragmentos.

    Trocea por **caracteres**, no por tokens: es una aproximación suficiente
    para el índice vectorial y evita cargar un tokenizador. (El grafo sí trocea
    por tokens, pero de eso se encarga LightRAG.)
    """

    def __init__(self, chunk_chars: int = 1200, overlap_chars: int = 150) -> None:
        if overlap_chars >= chunk_chars:
            raise ValueError("El solape debe ser menor que el tamaño de fragmento.")
        self._size = chunk_chars
        self._overlap = overlap_chars

    def split(self, text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        step = self._size - self._overlap
        return [text[i:i + self._size] for i in range(0, len(text), step)]

    def split_article(self, article: Article) -> list[str]:
        """Fragmentos de un artículo.

        El primero es la cabecera densa (título + palabras clave + resumen), que
        suele ser el fragmento que mejor representa el artículo entero.
        """
        header = article.dense_header
        chunks = [header] if header.strip() else []
        return chunks + self.split(article.text)
