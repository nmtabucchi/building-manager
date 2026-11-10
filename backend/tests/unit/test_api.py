from datetime import UTC, datetime
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.container import Container
from app.domain.exceptions import NotFoundError
from app.main import create_app

NOW = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
UID = "11111111-1111-1111-1111-111111111111"
BID = "aaaaaaaa-0000-0000-0000-000000000001"

BUILDING = {"id": BID, "nombre": "E", "direccion": "D", "localidad": "L", "provincia": "P",
            "informacion_general": None, "rol": "administrador", "total_documentos": 0,
            "created_at": NOW, "updated_at": NOW}
DOC = {"id": UID, "building_id": BID, "building_nombre": "E", "file_name": "a.pdf", "file_type": "pdf",
       "mime_type": "application/pdf", "size_bytes": 1, "storage_path": "SECRETO/ruta.pdf",
       "categoria": "otro", "status": "pendiente", "chunk_count": 0, "created_at": NOW, "updated_at": NOW}


class FakeSP:
    """Sustituye al StoredProcedureClient; registra llamadas y devuelve respuestas por SP."""

    def __init__(self):
        self.responses, self.calls = {}, []

    async def _run(self, name, params, auth):
        self.calls.append((name, params, auth))
        r = self.responses.get(name, [])
        if isinstance(r, Exception):
            raise r
        return r

    async def call(self, name, params=None, *, auth, read_only=False):
        return await self._run(name, params, auth)

    async def call_one(self, name, params=None, *, auth, read_only=False):
        return (await self._run(name, params, auth))[0]

    async def aclose(self):
        pass


def token(settings, **over):
    claims = {"sub": UID, "aud": "authenticated", "iss": settings.supabase_issuer,
              "exp": int(datetime.now(UTC).timestamp()) + 3600, "email": "a@b.c", **over}
    return jwt.encode(claims, settings.supabase_jwt_secret.get_secret_value(), algorithm="HS256")


@pytest.fixture
def sp():
    return FakeSP()


@pytest.fixture
def client(settings, sp):
    app = create_app(settings, Container(settings, sp_client=sp))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers(settings):
    return {"Authorization": f"Bearer {token(settings)}"}


def test_health_no_requiere_auth(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/me", "/dashboard", "/buildings", f"/buildings/{BID}", "/conversations"])
def test_endpoints_sin_token_devuelven_401(client, path):
    r = client.get("/api/v1" + path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_token_expirado_o_firma_invalida(client, settings):
    for bad in (token(settings, exp=1), token(settings, aud="otra"),
                jwt.encode({"sub": UID}, "otra-clave-" * 5, algorithm="HS256")):
        r = client.get("/api/v1/buildings", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401


def test_listar_edificios_usa_jwt_del_usuario(client, sp, headers):
    sp.responses["sp_building_listar_por_usuario"] = [BUILDING]
    r = client.get("/api/v1/buildings", headers=headers)
    assert r.status_code == 200 and r.json()[0]["nombre"] == "E"
    _, _, auth = sp.calls[0]
    assert auth.user_id == UUID(UID)


def test_crear_edificio_valida_entrada(client, headers):
    r = client.post("/api/v1/buildings", headers=headers, json={"nombre": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_crear_edificio(client, sp, headers):
    sp.responses["sp_building_crear"] = [BUILDING]
    body = {"nombre": "  Edificio  ", "direccion": "Calle 1", "localidad": "CABA", "provincia": "BA"}
    r = client.post("/api/v1/buildings", headers=headers, json=body)
    assert r.status_code == 201
    assert sp.calls[0][1]["p_nombre"] == "Edificio"


def test_not_found_se_traduce_a_404(client, sp, headers):
    sp.responses["sp_building_obtener_por_id"] = NotFoundError("Edificio no encontrado")
    r = client.get(f"/api/v1/buildings/{BID}", headers=headers)
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "Edificio no encontrado"
    assert r.json()["error"]["request_id"]


def test_id_invalido_es_422(client, headers):
    assert client.get("/api/v1/buildings/no-es-uuid", headers=headers).status_code == 422


def test_documento_no_expone_storage_path(client, sp, headers):
    sp.responses["sp_document_obtener_por_id"] = [DOC]
    r = client.get(f"/api/v1/documents/{UID}", headers=headers)
    assert r.status_code == 200
    assert "storage_path" not in r.json()
    assert "SECRETO" not in r.text


def test_eliminar_documento_204(client, sp, headers):
    sp.responses["sp_document_eliminar"] = [{"id": UID, "building_id": BID, "storage_path": "x", "eliminado": True}]
    assert client.delete(f"/api/v1/documents/{UID}", headers=headers).status_code == 204


def test_listar_documentos_con_filtros(client, sp, headers):
    sp.responses["sp_document_listar_por_edificio"] = [DOC]
    r = client.get(f"/api/v1/buildings/{BID}/documents?status=pendiente&categoria=otro", headers=headers)
    assert r.status_code == 200
    params = sp.calls[0][1]
    assert params["p_status"] == "pendiente" and params["p_categoria"] == "otro"
    assert client.get(f"/api/v1/buildings/{BID}/documents?status=zzz", headers=headers).status_code == 422


def test_miembros_asignar_y_quitar(client, sp, headers):
    sp.responses["sp_building_usuario_asignar"] = [{"user_id": UID, "email": "a@b.c", "rol": "lector", "created_at": NOW}]
    sp.responses["sp_building_usuario_quitar"] = [{"eliminado": True}]
    assert client.put(f"/api/v1/buildings/{BID}/members", headers=headers,
                      json={"email": "a@b.c", "rol": "lector"}).status_code == 200
    assert client.put(f"/api/v1/buildings/{BID}/members", headers=headers,
                      json={"email": "a@b.c", "rol": "superuser"}).status_code == 422
    assert client.delete(f"/api/v1/buildings/{BID}/members/{UID}", headers=headers).status_code == 204


def test_conversaciones_y_mensajes(client, sp, headers):
    conv = {"id": UID, "building_id": BID, "building_nombre": "E", "total_mensajes": 0,
            "created_at": NOW, "updated_at": NOW}
    sp.responses["sp_conversation_crear"] = [conv]
    sp.responses["sp_message_listar_por_conversacion"] = []
    r = client.post("/api/v1/conversations", headers=headers, json={"building_id": BID})
    assert r.status_code == 201
    assert client.get(f"/api/v1/conversations/{UID}/messages", headers=headers).json() == []
    assert client.get("/api/v1/conversations?limit=500", headers=headers).status_code == 422


def test_error_inesperado_no_filtra_detalles(settings, sp, headers):
    sp.responses["sp_dashboard_resumen"] = RuntimeError("password=secreto")
    app = create_app(settings, Container(settings, sp_client=sp))
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/dashboard", headers=headers)
    assert r.status_code == 500 and "secreto" not in r.text


# ------------------------------------------------------------- Etapa 3: carga
import io

from tests.helpers import make_pdf


class FakeStorage:
    def __init__(self):
        self.files = {}

    async def upload(self, path, data, content_type):
        self.files[path] = data

    async def delete(self, path):
        self.files.pop(path, None)

    async def signed_url(self, path, expires_in=300):
        return f"https://signed/{path}"


class FakeQueue:
    def __init__(self):
        self.ids = []

    async def enqueue(self, doc_id):
        self.ids.append(doc_id)

    async def start(self): pass
    async def stop(self): pass


@pytest.fixture
def upload_env(settings, sp):
    storage, queue = FakeStorage(), FakeQueue()
    app = create_app(settings, Container(settings, sp_client=sp, storage=storage, queue=queue))
    with TestClient(app) as c:
        yield c, storage, queue


def _post(c, headers, name, data, **form):
    return c.post(f"/api/v1/buildings/{BID}/documents", headers=headers,
                  files={"file": (name, io.BytesIO(data), "application/octet-stream")}, data=form)


def test_subir_documento_202(upload_env, sp, headers):
    c, storage, queue = upload_env
    sp.responses["sp_document_crear"] = [DOC]
    r = _post(c, headers, "reglamento.pdf", make_pdf(["hola"]), categoria="reglamento", titulo="Reglamento")
    assert r.status_code == 202 and "storage_path" not in r.json()
    params = sp.calls[0][1]
    assert params["p_categoria"] == "reglamento" and params["p_file_name"] == "reglamento.pdf"
    assert "SECRETO/ruta.pdf" in storage.files and queue.ids == [UUID(UID)]


def test_subir_tipo_invalido_415_y_no_toca_la_base(upload_env, sp, headers):
    c, storage, queue = upload_env
    r = _post(c, headers, "malware.exe", b"MZ....")
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert _post(c, headers, "falso.pdf", b"<html>").status_code == 415
    assert sp.calls == [] and queue.ids == []


def test_subir_archivo_demasiado_grande_413(upload_env, sp, headers):
    c, *_ = upload_env
    big = b"%PDF-" + b"0" * (20 * 1024 * 1024)
    r = _post(c, headers, "grande.pdf", big)
    assert r.status_code == 413 and sp.calls == []


def test_subir_sin_token_401_categoria_invalida_422(upload_env, headers):
    c, *_ = upload_env
    assert _post(c, {}, "a.pdf", make_pdf(["x"])).status_code == 401
    assert _post(c, headers, "a.pdf", make_pdf(["x"]), categoria="inexistente").status_code == 422


def test_lector_no_puede_subir_403(upload_env, sp, headers):
    from app.domain.exceptions import PermissionDeniedError
    c, storage, queue = upload_env
    sp.responses["sp_document_crear"] = PermissionDeniedError("Permisos insuficientes")
    assert _post(c, headers, "a.pdf", make_pdf(["x"])).status_code == 403
    assert storage.files == {} and queue.ids == []


def test_reprocesar_y_url_de_descarga(upload_env, sp, headers):
    c, storage, queue = upload_env
    sp.responses["sp_document_reprocesar"] = [DOC]
    sp.responses["sp_document_obtener_por_id"] = [DOC]
    assert c.post(f"/api/v1/documents/{UID}/reprocess", headers=headers).status_code == 202
    assert queue.ids == [UUID(UID)]
    r = c.get(f"/api/v1/documents/{UID}/download-url", headers=headers)
    assert r.json() == {"url": "https://signed/SECRETO/ruta.pdf", "expires_in": 300}


# ------------------------------------------------------------- Etapa 4: chat
import json as _json

from app.domain.exceptions import LLMUnavailableError
from app.infrastructure.llm.llm_provider import LLMProvider, LLMResult

CHUNK_ROW = {"chunk_id": "cccccccc-0000-0000-0000-000000000001", "document_id": UID, "building_id": BID,
             "file_name": "reglamento.pdf", "titulo": None, "categoria": "reglamento", "fecha_documento": None,
             "chunk_index": 0, "page_number": 4, "page_end": None, "content": "Se prohíben mascotas grandes.",
             "metadata": {}, "similarity": 0.8}
CONV = {"id": UID, "building_id": BID, "building_nombre": "Edificio Demo", "titulo": None, "total_mensajes": 0,
        "ultimo_mensaje_at": None, "created_at": NOW, "updated_at": NOW}


class ScriptedLLM(LLMProvider):
    def __init__(self, error=None):
        self.error = error

    async def generate_text(self, system, user, *, max_tokens, effort):
        return LLMResult("q", "m")

    async def generate_structured(self, system, user, schema, *, max_tokens, effort):
        if self.error:
            raise self.error
        data = {"respuesta": "Prohibidas [F1].", "cobertura": "completa", "interpretaciones": [],
                "citas": [{"fragmento_id": "F1", "cita_textual": "mascotas grandes"}]}
        return LLMResult(_json.dumps(data), "claude-test", {"input_tokens": 1, "output_tokens": 1}, data=data)


def _chat_client(settings, sp, llm, **over):
    s = settings.model_copy(update=over)
    return TestClient(create_app(s, Container(s, sp_client=sp, llm=llm)))


def _prepare(sp):
    def message(role):
        return {"id": UID, "conversation_id": UID, "role": role, "content": "x", "sources": [], "metadata": {}, "created_at": NOW}
    sp.responses.update({
        "sp_conversation_obtener_por_id": [CONV], "sp_message_listar_por_conversacion": [],
        "sp_chunk_buscar_similares": [CHUNK_ROW], "sp_message_crear": [message("user")]})


def test_preguntar_al_asistente_flujo_completo(settings, sp, headers):
    _prepare(sp)
    with _chat_client(settings, sp, ScriptedLLM()) as c:
        r = c.post(f"/api/v1/conversations/{UID}/messages", headers=headers, json={"content": "¿Hay mascotas?"})
    assert r.status_code == 201
    names = [n for n, *_ in sp.calls]
    assert names.index("sp_conversation_obtener_por_id") < names.index("sp_chunk_buscar_similares")
    assert names.count("sp_message_crear") == 2
    search = next(p for n, p, _ in sp.calls if n == "sp_chunk_buscar_similares")
    assert str(search["p_building_id"]) == BID and len(search["p_query_embedding"]) == 1024  # edificio sale de la conversación
    saved = [p for n, p, _ in sp.calls if n == "sp_message_crear"][1]
    assert saved["p_role"] == "assistant" and saved["p_sources"][0]["file_name"] == "reglamento.pdf"
    assert saved["p_metadata"]["cobertura"] == "completa"
    assert not any("service" in repr(a) for *_, a in sp.calls)


def test_preguntar_validaciones_y_auth(settings, sp, headers):
    _prepare(sp)
    with _chat_client(settings, sp, ScriptedLLM()) as c:
        url = f"/api/v1/conversations/{UID}/messages"
        assert c.post(url, json={"content": "hola"}).status_code == 401
        assert c.post(url, headers=headers, json={"content": "   "}).status_code == 422
        assert c.post(url, headers=headers, json={"content": "x" * 2001}).status_code == 422
    assert sp.calls == []


def test_error_de_claude_es_502(settings, sp, headers):
    _prepare(sp)
    with _chat_client(settings, sp, ScriptedLLM(LLMUnavailableError("Claude no disponible"))) as c:
        r = c.post(f"/api/v1/conversations/{UID}/messages", headers=headers, json={"content": "hola"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_ERROR"


def test_rate_limit_429(settings, sp, headers):
    _prepare(sp)
    with _chat_client(settings, sp, ScriptedLLM(), chat_rate_limit_per_minute=1) as c:
        url = f"/api/v1/conversations/{UID}/messages"
        assert c.post(url, headers=headers, json={"content": "uno"}).status_code == 201
        r = c.post(url, headers=headers, json={"content": "dos"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
