"""Limpieza y normalización del texto extraído."""
import re
import unicodedata
from collections import Counter

from app.rag.ingestion.models import ExtractedDocument, PageText

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PAGE_NUMBER = re.compile(r"^\s*(?:p[áa]g(?:ina|\.)?|page)?\s*\d{1,4}(?:\s*(?:de|/|of)\s*\d{1,4})?\s*$", re.IGNORECASE)


class TextCleaner:
    """Normaliza Unicode, repara cortes por guion, quita números de página y encabezados/pies repetidos."""

    def __init__(self, repeated_line_ratio: float = 0.5, min_pages_for_repeats: int = 3, max_header_len: int = 80):
        self._ratio = repeated_line_ratio
        self._min_pages = min_pages_for_repeats
        self._max_len = max_header_len

    def clean(self, doc: ExtractedDocument) -> ExtractedDocument:
        repeated = self._repeated_lines(doc.pages)
        pages = []
        for page in doc.pages:
            lines = [
                ln for ln in page.text.splitlines()
                if ln.strip() not in repeated and not _PAGE_NUMBER.match(ln)
            ]
            pages.append(PageText(page.page_number, self.clean_text("\n".join(lines))))
        return ExtractedDocument(pages=pages, page_count=doc.page_count)

    @staticmethod
    def clean_text(text: str) -> str:
        text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
        text = _CONTROL.sub("", text).replace(" ", " ").replace("­", "")
        text = _HYPHEN_BREAK.sub(r"\1\2", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _repeated_lines(self, pages: list[PageText]) -> set[str]:
        if len(pages) < self._min_pages:
            return set()
        counts: Counter[str] = Counter()
        for page in pages:
            counts.update({ln.strip() for ln in page.text.splitlines() if 0 < len(ln.strip()) <= self._max_len})
        threshold = len(pages) * self._ratio
        return {ln for ln, n in counts.items() if n > threshold}
