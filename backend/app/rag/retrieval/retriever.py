from uuid import UUID

from app.domain.auth import UserAuthContext
from app.domain.entities import RetrievedChunk
from app.domain.enums import DocumentCategory
from app.infrastructure.embeddings.embedding_provider import EmbeddingProvider
from app.repositories.document_and_conversation_repositories import ChunkRepository


class SupabaseRetriever:
    """Genera el embedding de la pregunta y delega la búsqueda al SP (sin SQL en Python).

    El edificio se filtra DENTRO de la base (membresía + building_id + RLS); aquí no hay filtrado de seguridad.
    """

    def __init__(self, embeddings: EmbeddingProvider, chunks: ChunkRepository):
        self._embeddings = embeddings
        self._chunks = chunks

    async def retrieve(self, auth: UserAuthContext, building_id: UUID, question: str, *, top_k: int,
                       min_similarity: float,
                       categorias: list[DocumentCategory] | None = None) -> list[RetrievedChunk]:
        vector = await self._embeddings.embed_query(question)
        return await self._chunks.buscar_similares(auth, building_id, vector, top_k, min_similarity, categorias)
