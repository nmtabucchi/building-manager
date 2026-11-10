"""Rutas REST (Etapa 2). Sin lógica de negocio: delegan en los servicios."""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel

from app.api.dependencies import get_auth_context, get_container
from app.core.container import Container
from app.domain.auth import UserAuthContext
from app.domain.entities import Building, Conversation, DashboardSummary, Member, Message, User
from app.domain.enums import DocumentCategory, DocumentStatus
from app.domain.exceptions import ValidationError
from app.schemas.schemas import (
    BuildingInput,
    ConversationInput,
    DocumentMetadataInput,
    DocumentOut,
    MemberInput,
    MessageInput,
)

router = APIRouter()
Auth = Depends(get_auth_context)
Ctr = Depends(get_container)


@router.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


@router.get("/me", response_model=User, tags=["me"])
async def me(auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.user_service.perfil(auth)


@router.get("/dashboard", response_model=DashboardSummary, tags=["dashboard"])
async def dashboard(auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.dashboard_service.resumen(auth)


# ------------------------------------------------------------------ edificios
@router.get("/buildings", response_model=list[Building], tags=["buildings"])
async def list_buildings(auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.building_service.listar(auth)


@router.post("/buildings", response_model=Building, status_code=status.HTTP_201_CREATED, tags=["buildings"])
async def create_building(body: BuildingInput, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.building_service.crear(auth, **body.model_dump())


@router.get("/buildings/{building_id}", response_model=Building, tags=["buildings"])
async def get_building(building_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.building_service.obtener(auth, building_id)


@router.put("/buildings/{building_id}", response_model=Building, tags=["buildings"])
async def update_building(building_id: UUID, body: BuildingInput, auth: UserAuthContext = Auth,
                          c: Container = Ctr):
    return await c.building_service.actualizar(auth, building_id, **body.model_dump())


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["buildings"])
async def delete_building(building_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    await c.building_service.eliminar(auth, building_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ miembros
@router.get("/buildings/{building_id}/members", response_model=list[Member], tags=["members"])
async def list_members(building_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.member_service.listar(auth, building_id)


@router.put("/buildings/{building_id}/members", response_model=Member, tags=["members"])
async def assign_member(building_id: UUID, body: MemberInput, auth: UserAuthContext = Auth,
                        c: Container = Ctr):
    return await c.member_service.asignar(auth, building_id, body.email, body.rol)


@router.delete("/buildings/{building_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               tags=["members"])
async def remove_member(building_id: UUID, user_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    await c.member_service.quitar(auth, building_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- documentos
@router.post("/buildings/{building_id}/documents", response_model=DocumentOut,
             status_code=status.HTTP_202_ACCEPTED, tags=["documents"])
async def upload_document(building_id: UUID, file: UploadFile = File(...),
                          categoria: DocumentCategory = Form(DocumentCategory.OTRO),
                          titulo: str | None = Form(None, max_length=255),
                          fecha_documento: date | None = Form(None),
                          auth: UserAuthContext = Auth, c: Container = Ctr):
    if fecha_documento is not None and fecha_documento > date.today():
        raise ValidationError("La fecha del documento no puede ser futura")
    limit = c.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)  # nunca se lee más de límite+1 bytes
    return await c.document_service.cargar(
        auth, building_id, file_name=file.filename or "", data=data,
        categoria=categoria, titulo=titulo, fecha_documento=fecha_documento)


@router.post("/documents/{document_id}/reprocess", response_model=DocumentOut,
             status_code=status.HTTP_202_ACCEPTED, tags=["documents"])
async def reprocess_document(document_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.document_service.reprocesar(auth, document_id)


@router.get("/documents/{document_id}/download-url", tags=["documents"])
async def document_download_url(document_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.document_service.url_descarga(auth, document_id)


@router.get("/buildings/{building_id}/documents", response_model=list[DocumentOut], tags=["documents"])
async def list_documents(building_id: UUID, status_: DocumentStatus | None = Query(default=None, alias="status"),
                         categoria: DocumentCategory | None = None, auth: UserAuthContext = Auth,
                         c: Container = Ctr):
    return await c.document_service.listar(auth, building_id, status_, categoria)


@router.get("/documents/{document_id}", response_model=DocumentOut, tags=["documents"])
async def get_document(document_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.document_service.obtener(auth, document_id)


@router.put("/documents/{document_id}", response_model=DocumentOut, tags=["documents"])
async def update_document(document_id: UUID, body: DocumentMetadataInput, auth: UserAuthContext = Auth,
                          c: Container = Ctr):
    return await c.document_service.actualizar_metadatos(auth, document_id, **body.model_dump())


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["documents"])
async def delete_document(document_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    await c.document_service.eliminar(auth, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------- conversaciones
@router.get("/conversations", response_model=list[Conversation], tags=["conversations"])
async def list_conversations(building_id: UUID | None = None, limit: int = Query(20, ge=1, le=100),
                             offset: int = Query(0, ge=0), auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.conversation_service.listar(auth, building_id, limit, offset)


@router.post("/conversations", response_model=Conversation, status_code=status.HTTP_201_CREATED,
             tags=["conversations"])
async def create_conversation(body: ConversationInput, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.conversation_service.crear(auth, body.building_id, body.titulo)


@router.get("/conversations/{conversation_id}", response_model=Conversation, tags=["conversations"])
async def get_conversation(conversation_id: UUID, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.conversation_service.obtener(auth, conversation_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[Message], tags=["conversations"])
async def list_messages(conversation_id: UUID, limit: int = Query(50, ge=1, le=200),
                        before: datetime | None = None, auth: UserAuthContext = Auth, c: Container = Ctr):
    return await c.conversation_service.mensajes(auth, conversation_id, limit, before)


class ChatExchange(BaseModel):
    user_message: Message
    assistant_message: Message


@router.post("/conversations/{conversation_id}/messages", response_model=ChatExchange,
             status_code=status.HTTP_201_CREATED, tags=["conversations"])
async def ask_assistant(conversation_id: UUID, body: MessageInput, auth: UserAuthContext = Auth,
                        c: Container = Ctr):
    user_message, assistant_message = await c.chat_service.preguntar(auth, conversation_id, body.content)
    return ChatExchange(user_message=user_message, assistant_message=assistant_message)
