"""Chunking que conserva la página de origen de cada fragmento."""
from bisect import bisect_right

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.models import ExtractedDocument, TextChunk

_PAGE_SEPARATOR = "\n\n"


class PageAwareChunker:
    """Concatena las páginas y divide con RecursiveCharacterTextSplitter.

    Con el offset de inicio de cada página se calcula, para cada chunk, la página inicial y final:
    un párrafo que cruza de página no se corta artificialmente y la cita sigue siendo precisa.
    """

    def __init__(self, chunk_size: int = 1200, chunk_overlap: int = 200):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            add_start_index=True,
        )

    def chunk(self, doc: ExtractedDocument, *, file_type: str) -> list[TextChunk]:
        parts, starts, pos = [], [], 0
        pages_with_text = [p for p in doc.pages if p.text.strip()]
        for page in pages_with_text:
            starts.append(pos)
            parts.append(page.text)
            pos += len(page.text) + len(_PAGE_SEPARATOR)
        full = _PAGE_SEPARATOR.join(parts)
        if not full.strip():
            return []

        chunks: list[TextChunk] = []
        for lc_doc in self._splitter.create_documents([full]):
            content = lc_doc.page_content.strip()
            if not content:
                continue
            start = lc_doc.metadata["start_index"]
            end = start + len(lc_doc.page_content) - 1
            first = pages_with_text[bisect_right(starts, start) - 1].page_number
            last = pages_with_text[bisect_right(starts, end) - 1].page_number
            chunks.append(TextChunk(
                chunk_index=len(chunks),
                content=content,
                page_number=first,
                page_end=last if first is not None and last != first else None,
                token_count=max(1, len(content) // 4),  # estimación; solo informativa
                metadata={"char_start": start, "file_type": file_type},
            ))
        return chunks
