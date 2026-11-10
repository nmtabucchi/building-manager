"""Entidades de dominio. Reflejan las filas que devuelven los stored procedures."""
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import BuildingRole, DocumentCategory, DocumentStatus, FileType, MessageRole


class Entity(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)


class User(Entity):
    id: UUID
    email: str
    full_name: str | None = None
    created_at: datetime


class Building(Entity):
    id: UUID
    nombre: str
    direccion: str
    localidad: str
    provincia: str
    informacion_general: str | None = None
    rol: BuildingRole
    total_documentos: int
    created_at: datetime
    updated_at: datetime


class Member(Entity):
    user_id: UUID
    email: str
    full_name: str | None = None
    rol: BuildingRole
    created_at: datetime


class Document(Entity):
    id: UUID
    building_id: UUID
    building_nombre: str
    file_name: str
    file_type: FileType
    mime_type: str
    size_bytes: int
    storage_path: str  # uso interno del backend; los schemas de respuesta no lo exponen
    categoria: DocumentCategory
    titulo: str | None = None
    fecha_documento: date | None = None
    status: DocumentStatus
    error_message: str | None = None
    page_count: int | None = None
    chunk_count: int
    uploaded_by: UUID | None = None
    uploaded_by_email: str | None = None
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class Conversation(Entity):
    id: UUID
    building_id: UUID
    building_nombre: str
    titulo: str | None = None
    total_mensajes: int
    ultimo_mensaje_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class Message(Entity):
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    sources: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: datetime


class DashboardSummary(Entity):
    total_edificios: int
    total_documentos: int
    documentos_pendientes: int
    documentos_procesando: int
    documentos_procesados: int
    documentos_con_error: int
    total_conversaciones: int


class RetrievedChunk(Entity):
    """Fragmento devuelto por la búsqueda semántica (sp_chunk_buscar_similares)."""

    chunk_id: UUID
    document_id: UUID
    building_id: UUID
    file_name: str
    titulo: str | None = None
    categoria: DocumentCategory
    fecha_documento: date | None = None
    chunk_index: int
    page_number: int | None = None
    page_end: int | None = None
    content: str
    metadata: dict[str, Any] = {}
    similarity: float
