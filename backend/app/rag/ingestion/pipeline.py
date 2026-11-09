"""Pipeline: descargar -> extraer -> limpiar -> chunkear -> embeber -> persistir."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.domain.enums import FileType
from app.domain.exceptions import NotFoundError
from app.infrastructure.embeddings.embedding_provider import EmbeddingProvider
from app.infrastructure.storage.storage_gateway import StorageGateway
from app.rag.ingestion.chunker import PageAwareChunker
from app.rag.ingestion.cleaner import TextCleaner
from app.rag.ingestion.extractors import extractor_for
from app.rag.ingestion.models import DocumentProcessingError
from app.repositories.ingestion_repository import IngestionRepository

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 50


@dataclass(frozen=True)
class PipelineResult:
    page_count: int | None
    chunk_count: int


class IngestionPipeline:
    """No autoriza usuarios (lo hace DocumentService antes de encolar) ni gestiona estados (IngestionService)."""

    def __init__(self, storage: StorageGateway, embeddings: EmbeddingProvider, repository: IngestionRepository,
                 cleaner: TextCleaner | None = None, chunker: PageAwareChunker | None = None,
                 batch_size: int = 50):
        self._storage = storage
        self._embeddings = embeddings
        self._repo = repository
        self._cleaner = cleaner or TextCleaner()
        self._chunker = chunker or PageAwareChunker()
        self._batch_size = batch_size

    async def run(self, document: dict[str, Any]) -> PipelineResult:
        document_id = UUID(str(document["id"]))
        file_type = FileType(document["file_type"])

        try:
            data = await self._storage.download(document["storage_path"])
        except NotFoundError as exc:  # no confundir con "documento eliminado" (eso lo detecta el repositorio)
            raise DocumentProcessingError("El archivo no se encontró en el almacenamiento") from exc
        extracted = await asyncio.to_thread(extractor_for(file_type).extract, data)  # CPU: fuera del event loop
        cleaned = self._cleaner.clean(extracted)

        total_chars = sum(len(p.text) for p in cleaned.pages)
        if total_chars < MIN_TEXT_CHARS:
            raise DocumentProcessingError(
                "El documento no contiene texto extraíble (posible PDF escaneado; el OCR no está soportado)")

        chunks = self._chunker.chunk(cleaned, file_type=file_type.value)
        if not chunks:
            raise DocumentProcessingError("No se pudo generar contenido a partir del documento")

        await self._repo.eliminar_chunks(document_id)  # idempotencia ante reintentos / reproceso
        for i in range(0, len(chunks), self._batch_size):
            batch = chunks[i:i + self._batch_size]
            vectors = await self._embeddings.embed_documents([c.content for c in batch])
            if len(vectors) != len(batch):
                raise DocumentProcessingError("El proveedor de embeddings devolvió una cantidad inesperada de vectores")
            payload = [{
                "chunk_index": c.chunk_index, "content": c.content, "page_number": c.page_number,
                "page_end": c.page_end, "token_count": c.token_count, "metadata": c.metadata, "embedding": v,
            } for c, v in zip(batch, vectors, strict=True)]
            await self._repo.insertar_chunks(document_id, self._embeddings.model_name, payload)

        logger.info("Documento %s: %d chunks", document_id, len(chunks))
        return PipelineResult(page_count=extracted.page_count, chunk_count=len(chunks))
