"""Repositorios de documentos, conversaciones y mensajes (migraciones 0007 y 0010).

La carga de archivos (sp_document_crear + Storage + ingesta) se completa en la Etapa 3;
aquí se exponen las operaciones de consulta, edición y baja.
"""
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.domain.auth import UserAuthContext
from app.domain.entities import Conversation, Document, Message
from app.domain.enums import DocumentCategory, DocumentStatus, FileType, MessageRole
from app.repositories.base_repository import BaseRepository


class DocumentRepository(BaseRepository):
    async def crear(self, auth: UserAuthContext, *, building_id: UUID, file_name: str, file_type: FileType,
                    mime_type: str, size_bytes: int, sha256: str, categoria: DocumentCategory,
                    titulo: str | None, fecha_documento: date | None) -> Document:
        row = await self._sp.call_one("sp_document_crear", {
            "p_building_id": building_id, "p_file_name": file_name, "p_file_type": file_type,
            "p_mime_type": mime_type, "p_size_bytes": size_bytes, "p_sha256": sha256,
            "p_categoria": categoria, "p_titulo": titulo, "p_fecha_documento": fecha_documento,
        }, auth=auth)
        return self._one(Document, row)

    async def listar_por_edificio(self, auth: UserAuthContext, building_id: UUID,
                                  status: DocumentStatus | None = None,
                                  categoria: DocumentCategory | None = None) -> list[Document]:
        rows = await self._sp.call("sp_document_listar_por_edificio", {
            "p_building_id": building_id, "p_status": status, "p_categoria": categoria,
        }, auth=auth, read_only=True)
        return self._many(Document, rows)

    async def obtener_por_id(self, auth: UserAuthContext, document_id: UUID) -> Document:
        row = await self._sp.call_one(
            "sp_document_obtener_por_id", {"p_document_id": document_id}, auth=auth, read_only=True)
        return self._one(Document, row)

    async def actualizar_metadatos(self, auth: UserAuthContext, document_id: UUID, *,
                                   categoria: DocumentCategory, titulo: str | None,
                                   fecha_documento: date | None) -> Document:
        row = await self._sp.call_one("sp_document_actualizar_metadatos", {
            "p_document_id": document_id, "p_categoria": categoria,
            "p_titulo": titulo, "p_fecha_documento": fecha_documento,
        }, auth=auth)
        return self._one(Document, row)

    async def eliminar(self, auth: UserAuthContext, document_id: UUID) -> dict[str, Any]:
        """Devuelve {id, building_id, storage_path, eliminado} para borrar el archivo en Storage."""
        return await self._sp.call_one("sp_document_eliminar", {"p_document_id": document_id}, auth=auth)

    async def reprocesar(self, auth: UserAuthContext, document_id: UUID) -> Document:
        row = await self._sp.call_one("sp_document_reprocesar", {"p_document_id": document_id}, auth=auth)
        return self._one(Document, row)


class ConversationRepository(BaseRepository):
    async def crear(self, auth: UserAuthContext, building_id: UUID, titulo: str | None) -> Conversation:
        row = await self._sp.call_one(
            "sp_conversation_crear", {"p_building_id": building_id, "p_titulo": titulo}, auth=auth)
        return self._one(Conversation, row)

    async def listar(self, auth: UserAuthContext, building_id: UUID | None = None,
                     limit: int = 20, offset: int = 0) -> list[Conversation]:
        rows = await self._sp.call("sp_conversation_listar", {
            "p_building_id": building_id, "p_limit": limit, "p_offset": offset,
        }, auth=auth, read_only=True)
        return self._many(Conversation, rows)

    async def obtener_por_id(self, auth: UserAuthContext, conversation_id: UUID) -> Conversation:
        row = await self._sp.call_one("sp_conversation_obtener_por_id", {
            "p_conversation_id": conversation_id}, auth=auth, read_only=True)
        return self._one(Conversation, row)


class MessageRepository(BaseRepository):
    async def crear(self, auth: UserAuthContext, conversation_id: UUID, role: MessageRole, content: str,
                    sources: list[dict[str, Any]] | None = None,
                    metadata: dict[str, Any] | None = None) -> Message:
        row = await self._sp.call_one("sp_message_crear", {
            "p_conversation_id": conversation_id, "p_role": role, "p_content": content,
            "p_sources": sources or [], "p_metadata": metadata or {},
        }, auth=auth)
        return self._one(Message, row)

    async def listar_por_conversacion(self, auth: UserAuthContext, conversation_id: UUID,
                                      limit: int = 50, antes_de: datetime | None = None) -> list[Message]:
        rows = await self._sp.call("sp_message_listar_por_conversacion", {
            "p_conversation_id": conversation_id, "p_limit": limit, "p_antes_de": antes_de,
        }, auth=auth, read_only=True)
        return self._many(Message, rows)
