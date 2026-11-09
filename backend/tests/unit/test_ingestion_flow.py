import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.domain.auth import UserAuthContext
from app.domain.entities import Document
from app.domain.enums import DocumentCategory, DocumentStatus
from app.domain.exceptions import ConflictError, NotFoundError, PermissionDeniedError, PersistenceUnavailableError
from app.infrastructure.embeddings.embedding_provider import FakeEmbeddingProvider
from app.infrastructure.queue.ingestion_queue import InMemoryIngestionQueue
from app.infrastructure.storage.storage_gateway import StorageGateway
from app.rag.ingestion.chunker import PageAwareChunker
from app.rag.ingestion.pipeline import IngestionPipeline
from app.services.ingestion_service import GENERIC_ERROR, IngestionService
from app.services.services import DocumentService
from tests.helpers import make_docx, make_pdf

DOC_ID = uuid4()
BID = uuid4()
AUTH = UserAuthContext(user_id=uuid4(), email=None, jwt="t")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class MemoryStorage(StorageGateway):
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.fail_upload = False
        self.fail_delete = False

    async def upload(self, path, data, content_type):
        if self.fail_upload:
            raise RuntimeError("boom")
        self.files[path] = data

    async def download(self, path):
        if path not in self.files:
            raise NotFoundError("no existe")
        return self.files[path]

    async def delete(self, path):
        if self.fail_delete:
            raise RuntimeError("boom")
        self.files.pop(path, None)

    async def signed_url(self, path, expires_in=300):
        return f"https://signed/{path}?e={expires_in}"


class FakeIngestionRepo:
    """Emula las transiciones del SP sp_ingesta_document_actualizar_estado."""

    def __init__(self, status="pendiente", file_type="pdf", path="b/d.pdf"):
        self.doc = {"id": str(DOC_ID), "building_id": str(BID), "file_type": file_type,
                    "storage_path": path, "status": status}
        self.states: list[tuple] = []
        self.batches: list[list[dict]] = []
        self.models: list[str] = []
        self.deleted_chunks = 0
        self.conflict_on_claim = False

    async def obtener_documento(self, document_id):
        return dict(self.doc)

    async def actualizar_estado(self, document_id, status, *, error_message=None, page_count=None, chunk_count=None):
        if status == DocumentStatus.PROCESANDO and self.conflict_on_claim:
            raise ConflictError("otro worker")
        self.states.append((status.value, error_message, page_count, chunk_count))
        self.doc["status"] = status.value
        return {}

    async def eliminar_chunks(self, document_id):
        self.deleted_chunks += 1
        return 0

    async def insertar_chunks(self, document_id, model, chunks):
        self.models.append(model)
        self.batches.append(chunks)
        return {}

    async def listar_pendientes(self, limit=50, minutos_estancado=15):
        return [{"id": str(DOC_ID)}]


def build(repo, storage, embeddings=None, batch_size=50, chunk_size=300):
    pipeline = IngestionPipeline(storage, embeddings or FakeEmbeddingProvider(), repo,
                                 chunker=PageAwareChunker(chunk_size, 30), batch_size=batch_size)
    return IngestionService(repo, pipeline)


LONG = " ".join(f"Articulo {i}: los propietarios deben respetar el reglamento de copropiedad." for i in range(40))


async def test_procesa_pdf_y_deja_documento_procesado():
    storage, repo = MemoryStorage(), FakeIngestionRepo()
    storage.files["b/d.pdf"] = make_pdf([LONG[:1500], LONG[1500:3000]])
    await build(repo, storage, batch_size=5).process(DOC_ID)

    assert [s[0] for s in repo.states] == ["procesando", "procesado"]
    _, _, pages, count = repo.states[-1]
    assert pages == 2 and count == sum(len(b) for b in repo.batches) and count > 5
    assert repo.deleted_chunks == 1
    assert all(len(b) <= 5 for b in repo.batches) and len(repo.batches) > 1
    first = repo.batches[0][0]
    assert first["page_number"] == 1 and len(first["embedding"]) == 1024 and first["chunk_index"] == 0
    assert repo.models == ["fake-hash"] * len(repo.batches)
    indexes = [c["chunk_index"] for b in repo.batches for c in b]
    assert indexes == list(range(len(indexes)))


async def test_procesa_docx_sin_numero_de_pagina():
    storage, repo = MemoryStorage(), FakeIngestionRepo(file_type="docx", path="b/d.docx")
    storage.files["b/d.docx"] = make_docx([("Titulo", "Heading 1"), (LONG, None)])
    await build(repo, storage).process(DOC_ID)
    assert repo.states[-1][0] == "procesado" and repo.states[-1][2] is None
    assert all(c["page_number"] is None for b in repo.batches for c in b)


async def test_pdf_sin_texto_termina_en_error_con_mensaje_claro():
    storage, repo = MemoryStorage(), FakeIngestionRepo()
    storage.files["b/d.pdf"] = make_pdf(["", ""])
    await build(repo, storage).process(DOC_ID)
    status, msg, *_ = repo.states[-1]
    assert status == "error" and "texto extraíble" in msg
    assert repo.batches == []


async def test_archivo_faltante_en_storage_o_falla_de_embeddings_dejan_error_generico():
    repo = FakeIngestionRepo()
    await build(repo, MemoryStorage()).process(DOC_ID)
    assert repo.states[-1] == ("error", "El archivo no se encontró en el almacenamiento", None, None)

    class Broken(FakeEmbeddingProvider):
        async def embed_documents(self, texts):
            raise PersistenceUnavailableError("proveedor caído")

    storage, repo = MemoryStorage(), FakeIngestionRepo()
    storage.files["b/d.pdf"] = make_pdf([LONG])
    await build(repo, storage, embeddings=Broken()).process(DOC_ID)
    assert repo.states[-1][0] == "error" and repo.states[-1][1] == GENERIC_ERROR


async def test_pdf_corrupto_da_mensaje_especifico():
    storage, repo = MemoryStorage(), FakeIngestionRepo()
    storage.files["b/d.pdf"] = b"%PDF-1.4 basura"
    await build(repo, storage).process(DOC_ID)
    assert "dañado" in repo.states[-1][1]


async def test_documento_estancado_en_procesando_se_recupera():
    storage, repo = MemoryStorage(), FakeIngestionRepo(status="procesando")
    storage.files["b/d.pdf"] = make_pdf([LONG])
    await build(repo, storage).process(DOC_ID)
    assert [s[0] for s in repo.states] == ["pendiente", "procesando", "procesado"]


@pytest.mark.parametrize("status", ["procesado", "error"])
async def test_no_procesa_documentos_que_no_estan_pendientes(status):
    repo = FakeIngestionRepo(status=status)
    await build(repo, MemoryStorage()).process(DOC_ID)
    assert repo.states == []


async def test_claim_perdido_ante_otro_worker_omite_el_documento():
    repo = FakeIngestionRepo()
    repo.conflict_on_claim = True
    await build(repo, MemoryStorage()).process(DOC_ID)
    assert repo.states == [] and repo.batches == []


async def test_documento_eliminado_no_rompe_el_worker():
    class Gone(FakeIngestionRepo):
        async def obtener_documento(self, document_id):
            raise NotFoundError("x")

    await build(Gone(), MemoryStorage()).process(DOC_ID)


# ---------------------------------------------------------------------- cola
async def test_cola_procesa_y_deduplica_y_sobrevive_a_errores():
    seen = []

    async def handler(doc_id):
        seen.append(doc_id)
        if len(seen) == 1:
            raise RuntimeError("falla del primero")

    q = InMemoryIngestionQueue(handler)
    a, b = uuid4(), uuid4()
    await q.enqueue(a)
    await q.enqueue(a)  # duplicado
    await q.enqueue(b)
    await q.start()
    await asyncio.wait_for(q.join(), 5)
    await q.stop()
    assert seen == [a, b]


# ------------------------------------------------------------- DocumentService
def _doc(status="pendiente") -> Document:
    return Document(
        id=DOC_ID, building_id=BID, building_nombre="E", file_name="a.pdf", file_type="pdf",
        mime_type="application/pdf", size_bytes=1, storage_path=f"{BID}/{DOC_ID}.pdf",
        categoria="otro", status=status, chunk_count=0, created_at=NOW, updated_at=NOW)


class FakeDocRepo:
    def __init__(self):
        self.calls, self.create_error = [], None

    async def crear(self, auth, **kw):
        self.calls.append(("crear", kw))
        if self.create_error:
            raise self.create_error
        return _doc()

    async def eliminar(self, auth, document_id):
        self.calls.append(("eliminar", document_id))
        return {"storage_path": f"{BID}/{DOC_ID}.pdf"}

    async def reprocesar(self, auth, document_id):
        self.calls.append(("reprocesar", document_id))
        return _doc()

    async def obtener_por_id(self, auth, document_id):
        return _doc("procesado")


class FakeQueue:
    def __init__(self):
        self.ids = []

    async def enqueue(self, document_id):
        self.ids.append(document_id)


def service(repo=None, storage=None, queue=None):
    return DocumentService(repo or FakeDocRepo(), storage or MemoryStorage(), queue or FakeQueue(), 1024 * 1024)


async def test_cargar_registra_sube_y_encola_en_ese_orden():
    repo, storage, queue = FakeDocRepo(), MemoryStorage(), FakeQueue()
    data = make_pdf(["hola"])
    doc = await service(repo, storage, queue).cargar(
        AUTH, BID, file_name="../Reglamento.pdf", data=data, categoria=DocumentCategory.REGLAMENTO,
        titulo="T", fecha_documento=None)
    kw = repo.calls[0][1]
    assert kw["file_name"] == "Reglamento.pdf" and kw["building_id"] == BID and len(kw["sha256"]) == 64
    assert storage.files[doc.storage_path] == data
    assert queue.ids == [DOC_ID]


async def test_cargar_sin_permiso_no_sube_ni_encola():
    repo, storage, queue = FakeDocRepo(), MemoryStorage(), FakeQueue()
    repo.create_error = PermissionDeniedError("lector")
    with pytest.raises(PermissionDeniedError):
        await service(repo, storage, queue).cargar(
            AUTH, BID, file_name="a.pdf", data=make_pdf(["x"]), categoria=DocumentCategory.OTRO,
            titulo=None, fecha_documento=None)
    assert storage.files == {} and queue.ids == []


async def test_cargar_si_falla_el_upload_revierte_el_registro():
    repo, storage, queue = FakeDocRepo(), MemoryStorage(), FakeQueue()
    storage.fail_upload = True
    with pytest.raises(PersistenceUnavailableError):
        await service(repo, storage, queue).cargar(
            AUTH, BID, file_name="a.pdf", data=make_pdf(["x"]), categoria=DocumentCategory.OTRO,
            titulo=None, fecha_documento=None)
    assert [c[0] for c in repo.calls] == ["crear", "eliminar"] and queue.ids == []


async def test_eliminar_borra_el_archivo_y_tolera_fallo_de_storage():
    repo, storage = FakeDocRepo(), MemoryStorage()
    storage.files[f"{BID}/{DOC_ID}.pdf"] = b"x"
    await service(repo, storage).eliminar(AUTH, DOC_ID)
    assert storage.files == {}
    storage.fail_delete = True
    await service(repo, storage).eliminar(AUTH, DOC_ID)  # no lanza


async def test_reprocesar_encola_y_url_de_descarga():
    queue = FakeQueue()
    s = service(queue=queue)
    await s.reprocesar(AUTH, DOC_ID)
    assert queue.ids == [DOC_ID]
    assert (await s.url_descarga(AUTH, DOC_ID)) == {"url": f"https://signed/{BID}/{DOC_ID}.pdf?e=300", "expires_in": 300}
