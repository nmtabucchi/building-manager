"""Repositorio del pipeline de ingesta. Siempre con contexto de servicio (service_role)."""
from typing import Any
from uuid import UUID

from app.domain.auth import ServiceAuthContext
from app.domain.enums import DocumentStatus
from app.repositories.base_repository import BaseRepository

_SERVICE = ServiceAuthContext()


class IngestionRepository(BaseRepository):
    async def obtener_documento(self, document_id: UUID) -> dict[str, Any]:
        return await self._sp.call_one("sp_ingesta_document_obtener", {"p_document_id": document_id},
                                       auth=_SERVICE, read_only=True)

    async def actualizar_estado(self, document_id: UUID, status: DocumentStatus, *, error_message: str | None = None,
                                page_count: int | None = None, chunk_count: int | None = None) -> dict[str, Any]:
        return await self._sp.call_one("sp_ingesta_document_actualizar_estado", {
            "p_document_id": document_id, "p_status": status, "p_error_message": error_message,
            "p_page_count": page_count, "p_chunk_count": chunk_count}, auth=_SERVICE)

    async def listar_pendientes(self, limit: int = 50, minutos_estancado: int = 15) -> list[dict[str, Any]]:
        return await self._sp.call("sp_ingesta_document_listar_pendientes", {
            "p_limit": limit, "p_minutos_estancado": minutos_estancado}, auth=_SERVICE, read_only=True)

    async def eliminar_chunks(self, document_id: UUID) -> int:
        row = await self._sp.call_one("sp_ingesta_chunks_eliminar_por_documento",
                                      {"p_document_id": document_id}, auth=_SERVICE)
        return row["eliminados"]

    async def insertar_chunks(self, document_id: UUID, embedding_model: str,
                              chunks: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._sp.call_one("sp_ingesta_chunks_insertar_lote", {
            "p_document_id": document_id, "p_embedding_model": embedding_model, "p_chunks": chunks},
            auth=_SERVICE)
