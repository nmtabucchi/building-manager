import json

import httpx
import pytest
import respx

from app.domain.enums import FileType
from app.domain.exceptions import (
    FileTooLargeError,
    InfrastructureError,
    NotFoundError,
    PersistenceUnavailableError,
    UnsupportedFileTypeError,
    ValidationError,
)
from app.infrastructure.embeddings import embedding_provider as ep
from app.infrastructure.embeddings.embedding_provider import (
    FakeEmbeddingProvider,
    VoyageEmbeddingProvider,
    build_embedding_provider,
)
from app.infrastructure.storage.storage_gateway import SupabaseStorageGateway
from app.services.file_validation import sanitize_file_name, validate_upload
from tests.helpers import make_docx, make_pdf


# ------------------------------------------------------------------- embeddings
async def test_fake_es_determinista_normalizado_y_dimension_correcta():
    p = FakeEmbeddingProvider()
    a, b = await p.embed_documents(["reglamento mascotas", "reglamento mascotas"])
    assert a == b and len(a) == 1024
    assert sum(v * v for v in a) == pytest.approx(1.0)
    assert await p.embed_query("reglamento mascotas") == a


@respx.mock
async def test_voyage_usa_input_type_y_ordena_por_index():
    route = respx.post(VoyageEmbeddingProvider.URL).mock(return_value=httpx.Response(200, json={
        "data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]}))
    p = VoyageEmbeddingProvider("key", "voyage-3.5")
    assert await p.embed_documents(["a", "b"]) == [[1.0], [2.0]]
    body = json.loads(route.calls[0].request.content)
    assert body["input_type"] == "document" and body["output_dimension"] == 1024
    assert route.calls[0].request.headers["authorization"] == "Bearer key"
    await p.embed_query("q")
    assert json.loads(route.calls[1].request.content)["input_type"] == "query"


@respx.mock
async def test_voyage_reintenta_429_y_falla_con_4xx(monkeypatch):
    async def no_sleep(_): pass
    monkeypatch.setattr(ep.asyncio, "sleep", no_sleep)
    route = respx.post(VoyageEmbeddingProvider.URL).mock(side_effect=[
        httpx.Response(429), httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})])
    assert await VoyageEmbeddingProvider("k", "m").embed_query("q") == [1.0]
    assert route.call_count == 2
    respx.post(VoyageEmbeddingProvider.URL).mock(return_value=httpx.Response(401))
    with pytest.raises(InfrastructureError):
        await VoyageEmbeddingProvider("bad", "m").embed_query("q")
    respx.post(VoyageEmbeddingProvider.URL).mock(return_value=httpx.Response(503))
    with pytest.raises(PersistenceUnavailableError):
        await VoyageEmbeddingProvider("k", "m", retries=2).embed_query("q")


async def test_voyage_sin_clave():
    with pytest.raises(InfrastructureError, match="EMBEDDING_API_KEY"):
        await VoyageEmbeddingProvider(None, "m").embed_query("q")


def test_dimension_distinta_a_la_base_falla_al_construir(settings):
    with pytest.raises(InfrastructureError, match="vector"):
        build_embedding_provider(settings.model_copy(update={"embedding_dimension": 768}))
    assert isinstance(build_embedding_provider(settings), FakeEmbeddingProvider)


# --------------------------------------------------------------------- storage
@pytest.fixture
def storage(settings):
    return SupabaseStorageGateway(settings)


@respx.mock
async def test_storage_upload_download_delete(storage):
    base = "http://supabase.test/storage/v1/object"
    up = respx.post(f"{base}/building-documents/b/d.pdf").mock(return_value=httpx.Response(200, json={}))
    down = respx.get(f"{base}/authenticated/building-documents/b/d.pdf").mock(
        return_value=httpx.Response(200, content=b"bytes"))
    rm = respx.delete(f"{base}/building-documents/b/d.pdf").mock(return_value=httpx.Response(200, json={}))
    await storage.upload("b/d.pdf", b"x", "application/pdf")
    assert await storage.download("b/d.pdf") == b"bytes"
    await storage.delete("b/d.pdf")
    req = up.calls[0].request
    assert req.headers["authorization"] == "Bearer service-key" and req.headers["x-upsert"] == "false"
    assert down.called and rm.called


@respx.mock
async def test_storage_url_firmada_y_errores(storage):
    respx.post("http://supabase.test/storage/v1/object/sign/building-documents/b/d.pdf").mock(
        return_value=httpx.Response(200, json={"signedURL": "/object/sign/building-documents/b/d.pdf?token=abc"}))
    url = await storage.signed_url("b/d.pdf", 300)
    assert url == "http://supabase.test/storage/v1/object/sign/building-documents/b/d.pdf?token=abc"
    respx.get(url__startswith="http://supabase.test/storage/v1/object/authenticated").mock(
        return_value=httpx.Response(400, json={"error": "Object not found"}))
    with pytest.raises(NotFoundError):
        await storage.download("x.pdf")
    respx.post(url__startswith="http://supabase.test/storage/v1/object/building").mock(return_value=httpx.Response(500))
    with pytest.raises(PersistenceUnavailableError):
        await storage.upload("x.pdf", b"x", "application/pdf")


# ------------------------------------------------------------ validación archivos
MB = 1024 * 1024


def test_acepta_pdf_y_docx_validos():
    pdf = validate_upload("Reglamento.PDF", make_pdf(["hola"]), 20 * MB)
    assert pdf.file_type == FileType.PDF and pdf.mime_type == "application/pdf" and len(pdf.sha256) == 64
    docx = validate_upload("acta.docx", make_docx([("hola", None)]), 20 * MB)
    assert docx.file_type == FileType.DOCX


@pytest.mark.parametrize("name,data,exc", [
    ("virus.exe", b"MZ", UnsupportedFileTypeError),
    ("falso.pdf", b"<html>no soy pdf</html>", UnsupportedFileTypeError),
    ("falso.docx", b"PK\x03\x04basura", UnsupportedFileTypeError),
    ("vacio.pdf", b"", ValidationError),
    ("sin_extension", b"%PDF-1.4", UnsupportedFileTypeError),
])
def test_rechaza_archivos_invalidos(name, data, exc):
    with pytest.raises(exc):
        validate_upload(name, data, 20 * MB)


def test_rechaza_zip_que_no_es_docx():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("otro.txt", "x")
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("a.docx", buf.getvalue(), 20 * MB)


def test_rechaza_archivo_grande():
    with pytest.raises(FileTooLargeError):
        validate_upload("a.pdf", b"%PDF-" + b"0" * 2048, 1024)


@pytest.mark.parametrize("raw,clean", [
    ("../../etc/passwd.pdf", "passwd.pdf"), ("C:\\temp\\acta.pdf", "acta.pdf"),
    ("a\x00b\n.pdf", "ab.pdf"), ("  reglamento 2024.pdf ", "reglamento 2024.pdf"),
])
def test_sanitiza_nombres(raw, clean):
    assert sanitize_file_name(raw) == clean


def test_nombre_vacio_o_enorme():
    for bad in ("", "   ", "a" * 300 + ".pdf"):
        with pytest.raises(ValidationError):
            sanitize_file_name(bad)
