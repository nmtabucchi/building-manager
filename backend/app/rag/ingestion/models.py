from dataclasses import dataclass, field
from typing import Any


class DocumentProcessingError(Exception):
    """Error esperable del documento (corrupto, sin texto, protegido). El mensaje es apto para el usuario."""


@dataclass(frozen=True)
class PageText:
    page_number: int | None  # None en formatos sin páginas reales (DOCX)
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[PageText]
    page_count: int | None


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    page_number: int | None
    page_end: int | None
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
