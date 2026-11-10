"""Servicios de aplicación. Orquestan repositorios; no tocan SQL ni HTTP."""
import logging
from datetime import date, datetime
from uuid import UUID

from app.domain.auth import UserAuthContext
from app.domain.entities import (
    Building,
    Conversation,
    DashboardSummary,
    Document,
    Member,
    Message,
    User,
)
from app.domain.enums import BuildingRole, DocumentCategory, DocumentStatus
from app.domain.exceptions import DomainError, PersistenceUnavailableError
from app.infrastructure.queue.ingestion_queue import IngestionQueue
from app.infrastructure.storage.storage_gateway import StorageGateway
from app.repositories.document_and_conversation_repositories import (
    ConversationRepository,
    DocumentRepository,
    MessageRepository,
)
from app.repositories.user_and_building_repositories import (
    BuildingRepository,
    DashboardRepository,
    MemberRepository,
    UserRepository,
)
from app.services.file_validation import validate_upload

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, users: UserRepository):
        self._users = users

    async def perfil(self, auth: UserAuthContext) -> User:
        return await self._users.obtener_actual(auth)


class DashboardService:
    def __init__(self, dashboard: DashboardRepository):
        self._dashboard = dashboard

    async def resumen(self, auth: UserAuthContext) -> DashboardSummary:
        return await self._dashboard.resumen(auth)


class BuildingService:
    def __init__(self, buildings: BuildingRepository):
        self._buildings = buildings

    async def listar(self, auth: UserAuthContext) -> list[Building]:
        return await self._buildings.listar_por_usuario(auth)

    async def obtener(self, auth: UserAuthContext, building_id: UUID) -> Building:
        return await self._buildings.obtener_por_id(auth, building_id)

    async def crear(self, auth: UserAuthContext, **datos) -> Building:
        return await self._buildings.crear(auth, **datos)

    async def actualizar(self, auth: UserAuthContext, building_id: UUID, **datos) -> Building:
        return await self._buildings.actualizar(auth, building_id, **datos)

    async def eliminar(self, auth: UserAuthContext, building_id: UUID) -> None:
        await self._buildings.eliminar(auth, building_id)


class MemberService:
    def __init__(self, members: MemberRepository):
        self._members = members

    async def listar(self, auth: UserAuthContext, building_id: UUID) -> list[Member]:
        return await self._members.listar(auth, building_id)

    async def asignar(self, auth: UserAuthContext, building_id: UUID, email: str, rol: BuildingRole) -> Member:
        return await self._members.asignar(auth, building_id, email, rol)

    async def quitar(self, auth: UserAuthContext, building_id: UUID, user_id: UUID) -> None:
        await self._members.quitar(auth, building_id, user_id)


class DocumentService:
    """Carga (validación + registro + Storage + encolado), consulta, edición, reproceso y baja."""

    DOWNLOAD_URL_TTL = 300

    def __init__(self, documents: DocumentRepository, storage: StorageGateway, queue: IngestionQueue,
                 max_upload_bytes: int):
        self._documents = documents
        self._storage = storage
        self._queue = queue
        self._max_bytes = max_upload_bytes

    async def cargar(self, auth: UserAuthContext, building_id: UUID, *, file_name: str, data: bytes,
                     categoria: DocumentCategory, titulo: str | None, fecha_documento: date | None) -> Document:
        f = validate_upload(file_name, data, self._max_bytes)
        # 1) registra (autoriza rol, duplicados y calcula storage_path) 2) sube 3) encola
        doc = await self._documents.crear(
            auth, building_id=building_id, file_name=f.file_name, file_type=f.file_type, mime_type=f.mime_type,
            size_bytes=f.size_bytes, sha256=f.sha256, categoria=categoria, titulo=titulo,
            fecha_documento=fecha_documento)
        try:
            await self._storage.upload(doc.storage_path, data, f.mime_type)
        except Exception as exc:
            logger.error("Upload fallido para %s; se revierte el registro", doc.id)
            try:
                await self._documents.eliminar(auth, doc.id)  # compensación
            except Exception:
                logger.exception("No se pudo revertir el registro %s", doc.id)
            if isinstance(exc, DomainError):
                raise
            raise PersistenceUnavailableError("No se pudo almacenar el archivo") from exc
        await self._queue.enqueue(doc.id)
        return doc

    async def listar(self, auth: UserAuthContext, building_id: UUID, status: DocumentStatus | None,
                     categoria: DocumentCategory | None) -> list[Document]:
        return await self._documents.listar_por_edificio(auth, building_id, status, categoria)

    async def obtener(self, auth: UserAuthContext, document_id: UUID) -> Document:
        return await self._documents.obtener_por_id(auth, document_id)

    async def actualizar_metadatos(self, auth: UserAuthContext, document_id: UUID, *,
                                   categoria: DocumentCategory, titulo: str | None,
                                   fecha_documento: date | None) -> Document:
        return await self._documents.actualizar_metadatos(
            auth, document_id, categoria=categoria, titulo=titulo, fecha_documento=fecha_documento)

    async def eliminar(self, auth: UserAuthContext, document_id: UUID) -> None:
        row = await self._documents.eliminar(auth, document_id)  # autoriza y borra fila + chunks
        try:
            await self._storage.delete(row["storage_path"])
        except Exception:  # el registro ya no existe: un archivo huérfano no debe fallar la operación
            logger.exception("Archivo huérfano en Storage: %s", row["storage_path"])

    async def reprocesar(self, auth: UserAuthContext, document_id: UUID) -> Document:
        doc = await self._documents.reprocesar(auth, document_id)
        await self._queue.enqueue(doc.id)
        return doc

    async def url_descarga(self, auth: UserAuthContext, document_id: UUID) -> dict:
        doc = await self._documents.obtener_por_id(auth, document_id)  # autoriza (membresía)
        url = await self._storage.signed_url(doc.storage_path, self.DOWNLOAD_URL_TTL)
        return {"url": url, "expires_in": self.DOWNLOAD_URL_TTL}


class ConversationService:
    """Etapa 2: conversaciones e historial. El envío de preguntas al RAG llega en la Etapa 4."""

    def __init__(self, conversations: ConversationRepository, messages: MessageRepository):
        self._conversations = conversations
        self._messages = messages

    async def crear(self, auth: UserAuthContext, building_id: UUID, titulo: str | None) -> Conversation:
        return await self._conversations.crear(auth, building_id, titulo)

    async def listar(self, auth: UserAuthContext, building_id: UUID | None, limit: int,
                     offset: int) -> list[Conversation]:
        return await self._conversations.listar(auth, building_id, limit, offset)

    async def obtener(self, auth: UserAuthContext, conversation_id: UUID) -> Conversation:
        return await self._conversations.obtener_por_id(auth, conversation_id)

    async def mensajes(self, auth: UserAuthContext, conversation_id: UUID, limit: int,
                       antes_de: datetime | None) -> list[Message]:
        return await self._messages.listar_por_conversacion(auth, conversation_id, limit, antes_de)
