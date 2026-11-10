"""Schemas de request/response de la API."""
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.entities import Document
from app.domain.enums import BuildingRole, DocumentCategory


class BuildingInput(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    direccion: str = Field(min_length=3, max_length=250)
    localidad: str = Field(min_length=2, max_length=120)
    provincia: str = Field(min_length=2, max_length=120)
    informacion_general: str | None = Field(default=None, max_length=5000)

    @field_validator("nombre", "direccion", "localidad", "provincia")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("no puede estar vacío")
        return v


class MemberInput(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    rol: BuildingRole


class DocumentMetadataInput(BaseModel):
    categoria: DocumentCategory
    titulo: str | None = Field(default=None, max_length=255)
    fecha_documento: date | None = None

    @field_validator("fecha_documento")
    @classmethod
    def _no_futura(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("la fecha del documento no puede ser futura")
        return v


class ConversationInput(BaseModel):
    building_id: UUID
    titulo: str | None = Field(default=None, max_length=200)


class DocumentOut(Document):
    """Documento sin `storage_path` (dato interno del backend)."""

    storage_path: str = Field(default="", exclude=True)


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("no puede estar vacío")
        return v
