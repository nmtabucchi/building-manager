"""Generadores de archivos de prueba (sin fixtures binarios en el repo)."""
import io

import pymupdf
from docx import Document as DocxDocument


def make_pdf(pages: list[str], encrypt_password: str | None = None) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 780), text, fontsize=10)
    if encrypt_password:
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=encrypt_password,
                           user_pw=encrypt_password)
    return doc.tobytes()


def make_docx(paragraphs: list[tuple[str, str | None]], table: list[list[str]] | None = None) -> bytes:
    d = DocxDocument()
    for text, style in paragraphs:
        if style and style.startswith("Heading"):
            d.add_heading(text, level=int(style[-1]))
        else:
            d.add_paragraph(text)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, val in enumerate(row):
                t.cell(r, c).text = val
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
