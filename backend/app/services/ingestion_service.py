"""Gestión de estados del procesamiento de un documento."""
import logging
from uuid import UUID

from app.domain.enums import DocumentStatus
from app.domain.exceptions import ConflictError, NotFoundError
from app.rag.ingestion.models import DocumentProcessingError
from app.rag.ingestion.pipeline import IngestionPipeline
from app.repositories.ingestion_repository import IngestionRepository

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Error interno durante el procesamiento. Use 'reprocesar' para reintentar."


class IngestionService:
    def __init__(self, repository: IngestionRepository, pipeline: IngestionPipeline):
        self._repo = repository
        self._pipeline = pipeline

    async def process(self, document_id: UUID) -> None:
        """Procesa un documento. Nunca lanza: cualquier fallo deja el documento en estado 'error'."""
        try:
            doc = await self._repo.obtener_documento(document_id)
        except NotFoundError:
            logger.info("Documento %s ya no existe; se omite", document_id)
            return

        status = DocumentStatus(doc["status"])
        try:
            if status == DocumentStatus.PROCESANDO:  # estancado por caída de un worker
                await self._repo.actualizar_estado(document_id, DocumentStatus.PENDIENTE)
            elif status != DocumentStatus.PENDIENTE:
                logger.info("Documento %s en estado %s; se omite", document_id, status)
                return
            await self._repo.actualizar_estado(document_id, DocumentStatus.PROCESANDO)  # claim exclusivo
        except ConflictError:
            logger.info("Documento %s tomado por otro worker", document_id)
            return
        except NotFoundError:
            return

        try:
            result = await self._pipeline.run(doc)
            await self._repo.actualizar_estado(
                document_id, DocumentStatus.PROCESADO, page_count=result.page_count, chunk_count=result.chunk_count)
        except DocumentProcessingError as exc:
            await self._fail(document_id, str(exc))
        except NotFoundError:
            logger.info("Documento %s eliminado durante el procesamiento", document_id)
        except Exception:
            logger.exception("Fallo procesando el documento %s", document_id)
            await self._fail(document_id, GENERIC_ERROR)

    async def _fail(self, document_id: UUID, message: str) -> None:
        try:
            await self._repo.actualizar_estado(document_id, DocumentStatus.ERROR, error_message=message)
        except Exception:
            logger.exception("No se pudo registrar el error del documento %s", document_id)

    async def pendientes(self) -> list[UUID]:
        rows = await self._repo.listar_pendientes()
        return [UUID(str(r["id"])) for r in rows]
