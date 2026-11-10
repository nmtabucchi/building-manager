"""Caso de uso: preguntar al asistente dentro de una conversación."""
from typing import Any
from uuid import UUID

from app.core.rate_limit import SlidingWindowRateLimiter
from app.domain.auth import UserAuthContext
from app.domain.entities import Message
from app.domain.enums import MessageRole
from app.repositories.document_and_conversation_repositories import ConversationRepository, MessageRepository


class ChatService:
    def __init__(self, conversations: ConversationRepository, messages: MessageRepository, graph: Any,
                 rate_limiter: SlidingWindowRateLimiter):
        self._conversations = conversations
        self._messages = messages
        self._graph = graph
        self._limiter = rate_limiter

    async def preguntar(self, auth: UserAuthContext, conversation_id: UUID, content: str) -> tuple[Message, Message]:
        self._limiter.check(auth.user_id)
        # autoriza (propiedad + membresía vigente) y obtiene el edificio: nunca viene del cliente
        conversation = await self._conversations.obtener_por_id(auth, conversation_id)
        user_message = await self._messages.crear(auth, conversation_id, MessageRole.USER, content)

        # si el grafo falla (Claude caído, etc.) la pregunta queda guardada y el error se propaga
        result = await self._graph.ainvoke({
            "auth": auth, "building_id": conversation.building_id, "building_nombre": conversation.building_nombre,
            "conversation_id": conversation_id, "question": content,
        })
        assistant_message = await self._messages.crear(
            auth, conversation_id, MessageRole.ASSISTANT, result["answer"], result["sources"], result["metadata"])
        return user_message, assistant_message
