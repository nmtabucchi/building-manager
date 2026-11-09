"""Composición de dependencias (inyección). Un contenedor por aplicación."""
import logging

from app.core.config import Settings
from app.core.security import SupabaseJwtVerifier
from app.infrastructure.database.stored_procedure_client import StoredProcedureClient
from app.infrastructure.embeddings.embedding_provider import EmbeddingProvider, build_embedding_provider
from app.infrastructure.queue.ingestion_queue import IngestionQueue, InMemoryIngestionQueue
from app.infrastructure.storage.storage_gateway import StorageGateway, SupabaseStorageGateway
from app.rag.ingestion.chunker import PageAwareChunker
from app.rag.ingestion.pipeline import IngestionPipeline
from app.repositories.document_and_conversation_repositories import (
    ConversationRepository, DocumentRepository, MessageRepository,
)
from app.repositories.ingestion_repository import IngestionRepository
from app.repositories.user_and_building_repositories import (
    BuildingRepository, DashboardRepository, MemberRepository, UserRepository,
)
from app.services.ingestion_service import IngestionService
from app.services.services import (
    BuildingService, ConversationService, DashboardService, DocumentService, MemberService, UserService,
)

logger = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings, sp_client: StoredProcedureClient | None = None,
                 jwt_verifier: SupabaseJwtVerifier | None = None, storage: StorageGateway | None = None,
                 embeddings: EmbeddingProvider | None = None, queue: IngestionQueue | None = None):
        self.settings = settings
        self.sp_client = sp_client or StoredProcedureClient(settings)
        self.jwt_verifier = jwt_verifier or SupabaseJwtVerifier(settings)
        self.storage = storage or SupabaseStorageGateway(settings)
        self.embeddings = embeddings or build_embedding_provider(settings)

        sp = self.sp_client
        ingestion_repo = IngestionRepository(sp)
        pipeline = IngestionPipeline(
            self.storage, self.embeddings, ingestion_repo,
            chunker=PageAwareChunker(settings.chunk_size, settings.chunk_overlap),
            batch_size=settings.ingestion_batch_size)
        self.ingestion_service = IngestionService(ingestion_repo, pipeline)
        self.ingestion_queue = queue or InMemoryIngestionQueue(self.ingestion_service.process)

        self.user_service = UserService(UserRepository(sp))
        self.dashboard_service = DashboardService(DashboardRepository(sp))
        self.building_service = BuildingService(BuildingRepository(sp))
        self.member_service = MemberService(MemberRepository(sp))
        self.document_service = DocumentService(
            DocumentRepository(sp), self.storage, self.ingestion_queue, settings.max_upload_mb * 1024 * 1024)
        self.conversation_service = ConversationService(ConversationRepository(sp), MessageRepository(sp))

    async def start(self) -> None:
        """Arranca el worker y re-encola documentos pendientes o estancados (recuperación tras reinicio)."""
        if not self.settings.ingestion_enabled:
            return
        await self.ingestion_queue.start()
        try:
            for document_id in await self.ingestion_service.pendientes():
                await self.ingestion_queue.enqueue(document_id)
        except Exception:
            logger.exception("No se pudo recuperar la lista de documentos pendientes")

    async def aclose(self) -> None:
        await self.ingestion_queue.stop()
        await self.sp_client.aclose()
