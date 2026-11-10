from typing import Any, TypedDict
from uuid import UUID

from app.domain.auth import UserAuthContext
from app.domain.entities import Message, RetrievedChunk


class RagState(TypedDict, total=False):
    # entrada
    auth: UserAuthContext
    building_id: UUID
    building_nombre: str
    conversation_id: UUID
    question: str
    # contexto
    history: list[Message]
    intent: str  # gancho para enrutar a agentes especializados en el futuro
    standalone_question: str
    # recuperación
    retrieved_chunks: list[RetrievedChunk]
    fragments: list[tuple[str, RetrievedChunk]]  # [("F1", chunk), ...] enviados a Claude
    # generación y validación
    draft: dict[str, Any]
    feedback: str | None
    retries: int
    needs_retry: bool
    no_info: bool
    refusal: bool
    validation: str  # ok | parcial | sin_citas_validas
    usage: dict[str, int]
    model: str
    started_at: float
    # salida
    answer: str
    sources: list[dict[str, Any]]
    coverage: str
    metadata: dict[str, Any]
