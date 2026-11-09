"""Extracción de texto. Un extractor por formato, intercambiables."""
import io
from abc import ABC, abstractmethod

from app.domain.enums import FileType
from app.rag.ingestion.models import DocumentProcessingError, ExtractedDocument, PageText


class TextExtractor(ABC):
    @abstractmethod
    def extract(self, data: bytes) -> ExtractedDocument: ...


class PdfExtractor(TextExtractor):
    """PDF con PyMuPDF: una entrada por página (numeración desde 1)."""

    def extract(self, data: bytes) -> ExtractedDocument:
        import pymupdf  # import diferido: la licencia AGPL queda aislada en este módulo

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise DocumentProcessingError("El PDF está dañado o no se pudo abrir") from exc
        with doc:
            if doc.needs_pass:
                raise DocumentProcessingError("El PDF está protegido con contraseña")
            pages = [PageText(i + 1, page.get_text("text")) for i, page in enumerate(doc)]
            return ExtractedDocument(pages=pages, page_count=len(pages))


class DocxExtractor(TextExtractor):
    """DOCX con python-docx. No hay páginas reales: se devuelve una sola 'página' sin número.

    Se respeta el orden del documento (párrafos y tablas); los títulos quedan separados por línea en blanco
    y las tablas se convierten a texto fila por fila con celdas separadas por ' | '.
    """

    def extract(self, data: bytes) -> ExtractedDocument:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        try:
            doc = Document(io.BytesIO(data))
        except Exception as exc:
            raise DocumentProcessingError("El archivo DOCX está dañado o no se pudo abrir") from exc

        parts: list[str] = []
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(child, doc)
                text = p.text.strip()
                if not text:
                    continue
                style = (p.style.name or "").lower() if p.style is not None else ""
                is_heading = style.startswith(("heading", "título", "titulo", "title"))
                parts.append(f"\n{text}\n" if is_heading else text)
            elif tag == "tbl":
                for row in Table(child, doc).rows:
                    cells: list[str] = []
                    for cell in row.cells:
                        txt = cell.text.strip().replace("\n", " ")
                        if txt and (not cells or cells[-1] != txt):  # celdas combinadas repiten texto
                            cells.append(txt)
                    if cells:
                        parts.append(" | ".join(cells))
        return ExtractedDocument(pages=[PageText(None, "\n".join(parts))], page_count=None)


def extractor_for(file_type: FileType) -> TextExtractor:
    return {FileType.PDF: PdfExtractor, FileType.DOCX: DocxExtractor}[file_type]()
