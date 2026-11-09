import pytest

from app.domain.enums import FileType
from app.rag.ingestion.chunker import PageAwareChunker
from app.rag.ingestion.cleaner import TextCleaner
from app.rag.ingestion.extractors import DocxExtractor, PdfExtractor, extractor_for
from app.rag.ingestion.models import DocumentProcessingError, ExtractedDocument, PageText
from tests.helpers import make_docx, make_pdf


# ------------------------------------------------------------------ extractores
def test_pdf_extrae_una_entrada_por_pagina():
    doc = PdfExtractor().extract(make_pdf(["Articulo uno sobre mascotas", "Articulo dos sobre ruidos"]))
    assert doc.page_count == 2
    assert [p.page_number for p in doc.pages] == [1, 2]
    assert "mascotas" in doc.pages[0].text and "ruidos" in doc.pages[1].text


def test_pdf_sin_texto_devuelve_paginas_vacias():
    doc = PdfExtractor().extract(make_pdf(["", ""]))
    assert doc.page_count == 2 and all(not p.text.strip() for p in doc.pages)


def test_pdf_corrupto_y_protegido():
    with pytest.raises(DocumentProcessingError, match="dañado"):
        PdfExtractor().extract(b"%PDF-1.4 esto no es un pdf")
    with pytest.raises(DocumentProcessingError, match="contraseña"):
        PdfExtractor().extract(make_pdf(["secreto"], encrypt_password="clave"))


def test_docx_conserva_titulos_y_tablas_en_orden():
    data = make_docx([("Capitulo I", "Heading 1"), ("Texto del primer capitulo.", None)],
                     table=[["Rubro", "Monto"], ["Expensas", "1000"]])
    doc = DocxExtractor().extract(data)
    text = doc.pages[0].text
    assert doc.page_count is None and doc.pages[0].page_number is None
    assert text.index("Capitulo I") < text.index("Texto del primer") < text.index("Rubro | Monto")
    assert "Expensas | 1000" in text


def test_docx_corrupto():
    with pytest.raises(DocumentProcessingError):
        DocxExtractor().extract(b"PK no es un docx")


def test_extractor_for():
    assert isinstance(extractor_for(FileType.PDF), PdfExtractor)
    assert isinstance(extractor_for(FileType.DOCX), DocxExtractor)


# --------------------------------------------------------------------- limpieza
def test_clean_text_normaliza():
    raw = "Re-\nglamento   de copropiedad\x00\r\n\r\n\r\n\r\nFin"
    assert TextCleaner.clean_text(raw) == "Reglamento de copropiedad\n\nFin"


def test_clean_text_unicode_nfc():
    assert TextCleaner.clean_text("café") == "café"


def test_elimina_encabezados_repetidos_y_numeros_de_pagina():
    pages = [PageText(i, f"CONSORCIO DEMO\nContenido unico {i}\nPágina {i} de 4") for i in range(1, 5)]
    out = TextCleaner().clean(ExtractedDocument(pages, 4))
    for i, p in enumerate(out.pages, 1):
        assert p.text == f"Contenido unico {i}"


def test_no_elimina_repetidos_con_pocas_paginas():
    pages = [PageText(1, "Titulo\nA"), PageText(2, "Titulo\nB")]
    out = TextCleaner().clean(ExtractedDocument(pages, 2))
    assert "Titulo" in out.pages[0].text


# ---------------------------------------------------------------------- chunker
def _paragraphs(prefix: str, n: int) -> str:
    return "\n\n".join(f"{prefix} parrafo {i}. " + "texto de relleno " * 20 for i in range(n))


def test_chunks_asignan_pagina_correcta():
    doc = ExtractedDocument([PageText(1, _paragraphs("uno", 6)), PageText(2, _paragraphs("dos", 6))], 2)
    chunks = PageAwareChunker(chunk_size=500, chunk_overlap=50).chunk(doc, file_type="pdf")
    assert len(chunks) > 4
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].page_number == 1
    assert chunks[-1].page_number in (1, 2) and (chunks[-1].page_end or chunks[-1].page_number) == 2
    for c in chunks:
        assert len(c.content) <= 500
        if c.page_end is not None:
            assert c.page_end > c.page_number
        if "dos parrafo" in c.content and "uno parrafo" not in c.content:
            assert (c.page_number, c.page_end) in ((2, None), (1, 2))
    assert any(c.page_number == 2 for c in chunks)


def test_chunk_que_cruza_paginas_informa_page_end():
    # ambas páginas caben juntas en un chunk (300 + 2 + 300 < 700): el chunk abarca dos páginas
    doc = ExtractedDocument([PageText(1, "a " * 150), PageText(2, "b " * 150)], 2)
    chunks = PageAwareChunker(chunk_size=700, chunk_overlap=0).chunk(doc, file_type="pdf")
    assert any(c.page_number == 1 and c.page_end == 2 for c in chunks)


def test_docx_sin_paginas():
    doc = ExtractedDocument([PageText(None, _paragraphs("x", 8))], None)
    chunks = PageAwareChunker(chunk_size=400, chunk_overlap=40).chunk(doc, file_type="docx")
    assert chunks and all(c.page_number is None and c.page_end is None for c in chunks)
    assert chunks[0].metadata["file_type"] == "docx"


def test_paginas_vacias_se_ignoran_y_documento_vacio_no_genera_chunks():
    doc = ExtractedDocument([PageText(1, ""), PageText(2, "contenido real " * 10)], 2)
    chunks = PageAwareChunker().chunk(doc, file_type="pdf")
    assert chunks and chunks[0].page_number == 2
    assert PageAwareChunker().chunk(ExtractedDocument([PageText(1, "  ")], 1), file_type="pdf") == []
