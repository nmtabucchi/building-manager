"""Cada método de repositorio invoca exactamente el SP de la matriz del catálogo."""
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.domain.auth import UserAuthContext
from app.domain.enums import BuildingRole, DocumentCategory, FileType, MessageRole
from app.repositories.document_and_conversation_repositories import (
    ConversationRepository, DocumentRepository, MessageRepository,
)
from app.repositories.user_and_building_repositories import (
    BuildingRepository, DashboardRepository, MemberRepository, UserRepository,
)

UID = UUID("11111111-1111-1111-1111-111111111111")
BID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
AUTH = UserAuthContext(user_id=UID, email=None, jwt="t")

BUILDING = {"id": str(BID), "nombre": "E", "direccion": "D", "localidad": "L", "provincia": "P",
            "informacion_general": None, "rol": "administrador", "total_documentos": 0,
            "created_at": NOW, "updated_at": NOW}
DOC = {"id": str(UID), "building_id": str(BID), "building_nombre": "E", "file_name": "a.pdf",
       "file_type": "pdf", "mime_type": "application/pdf", "size_bytes": 1, "storage_path": "x",
       "categoria": "otro", "status": "pendiente", "chunk_count": 0, "created_at": NOW, "updated_at": NOW}
CONV = {"id": str(UID), "building_id": str(BID), "building_nombre": "E", "total_mensajes": 0,
        "created_at": NOW, "updated_at": NOW}
MSG = {"id": str(UID), "conversation_id": str(UID), "role": "user", "content": "hola", "sources": [],
       "metadata": {}, "created_at": NOW}
MEMBER = {"user_id": str(UID), "email": "a@b.c", "rol": "lector", "created_at": NOW}


class FakeSP:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def call(self, name, params, *, auth, read_only=False):
        self.calls.append((name, params, read_only))
        return self.rows

    async def call_one(self, name, params, *, auth, read_only=False):
        self.calls.append((name, params, read_only))
        return self.rows[0]


async def _check(repo_cls, rows, method, args, kwargs, sp_name, read_only):
    sp = FakeSP(rows)
    await getattr(repo_cls(sp), method)(AUTH, *args, **kwargs)
    assert len(sp.calls) == 1, "un método = una llamada a un SP"
    name, params, ro = sp.calls[0]
    assert name == sp_name
    assert ro is read_only
    assert all(k.startswith("p_") for k in params)


CASES = [
    (UserRepository, [{"id": str(UID), "email": "a@b.c", "created_at": NOW}], "obtener_actual", (), {}, "sp_user_obtener_actual", True),
    (BuildingRepository, [BUILDING], "crear", (), dict(nombre="E", direccion="D", localidad="L", provincia="P", informacion_general=None), "sp_building_crear", False),
    (BuildingRepository, [BUILDING], "actualizar", (BID,), dict(nombre="E", direccion="D", localidad="L", provincia="P", informacion_general=None), "sp_building_actualizar", False),
    (BuildingRepository, [{"id": 1}], "eliminar", (BID,), {}, "sp_building_eliminar", False),
    (BuildingRepository, [BUILDING], "obtener_por_id", (BID,), {}, "sp_building_obtener_por_id", True),
    (BuildingRepository, [BUILDING], "listar_por_usuario", (), {}, "sp_building_listar_por_usuario", True),
    (MemberRepository, [MEMBER], "listar", (BID,), {}, "sp_building_usuario_listar", True),
    (MemberRepository, [MEMBER], "asignar", (BID, "a@b.c", BuildingRole.LECTOR), {}, "sp_building_usuario_asignar", False),
    (MemberRepository, [{"x": 1}], "quitar", (BID, UID), {}, "sp_building_usuario_quitar", False),
    (DashboardRepository, [dict(total_edificios=1, total_documentos=2, documentos_pendientes=0, documentos_procesando=0, documentos_procesados=2, documentos_con_error=0, total_conversaciones=0)], "resumen", (), {}, "sp_dashboard_resumen", True),
    (DocumentRepository, [DOC], "crear", (), dict(building_id=BID, file_name="a.pdf", file_type=FileType.PDF, mime_type="application/pdf", size_bytes=1, sha256="a" * 64, categoria=DocumentCategory.OTRO, titulo=None, fecha_documento=None), "sp_document_crear", False),
    (DocumentRepository, [DOC], "listar_por_edificio", (BID,), {}, "sp_document_listar_por_edificio", True),
    (DocumentRepository, [DOC], "obtener_por_id", (UID,), {}, "sp_document_obtener_por_id", True),
    (DocumentRepository, [DOC], "actualizar_metadatos", (UID,), dict(categoria=DocumentCategory.OTRO, titulo=None, fecha_documento=None), "sp_document_actualizar_metadatos", False),
    (DocumentRepository, [{"storage_path": "x"}], "eliminar", (UID,), {}, "sp_document_eliminar", False),
    (DocumentRepository, [DOC], "reprocesar", (UID,), {}, "sp_document_reprocesar", False),
    (ConversationRepository, [CONV], "crear", (BID, None), {}, "sp_conversation_crear", False),
    (ConversationRepository, [CONV], "listar", (), {}, "sp_conversation_listar", True),
    (ConversationRepository, [CONV], "obtener_por_id", (UID,), {}, "sp_conversation_obtener_por_id", True),
    (MessageRepository, [MSG], "crear", (UID, MessageRole.USER, "hola"), {}, "sp_message_crear", False),
    (MessageRepository, [MSG], "listar_por_conversacion", (UID,), {}, "sp_message_listar_por_conversacion", True),
]


@pytest.mark.parametrize("repo,rows,method,args,kwargs,sp,ro", CASES, ids=[c[5] for c in CASES])
async def test_metodo_invoca_su_sp(repo, rows, method, args, kwargs, sp, ro):
    await _check(repo, rows, method, args, kwargs, sp, ro)


async def test_eliminar_documento_devuelve_storage_path():
    sp = FakeSP([{"id": str(UID), "building_id": str(BID), "storage_path": "b/d.pdf", "eliminado": True}])
    result = await DocumentRepository(sp).eliminar(AUTH, UID)
    assert result["storage_path"] == "b/d.pdf"
