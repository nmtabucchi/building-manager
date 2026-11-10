"""Pruebas de integración de extremo a extremo contra Supabase LOCAL (Docker + Supabase CLI).

    supabase start && supabase db reset
    # exportar SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY (y SUPABASE_JWT_SECRET si aplica)
    cd backend && .venv/Scripts/python -m pytest -m integration

Usan el backend real (StoredProcedureClient, Storage, ingesta, grafo RAG) con embeddings falsos y un LLM
simulado: no consumen Claude ni Voyage. Cada ejecución crea usuarios nuevos; no limpian la base.
"""
import io
import json
import os
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.infrastructure.embeddings.embedding_provider import FakeEmbeddingProvider
from app.infrastructure.llm.llm_provider import LLMProvider, LLMResult
from app.main import create_app
from tests.helpers import make_docx

pytestmark = pytest.mark.integration

URL = os.environ.get("SUPABASE_URL")
ANON = os.environ.get("SUPABASE_ANON_KEY")
SERVICE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


def _reachable() -> bool:
    if not (URL and ANON and SERVICE):
        return False
    try:
        return httpx.get(f"{URL}/auth/v1/health", headers={"apikey": ANON}, timeout=3).status_code < 500
    except httpx.HTTPError:
        return False


if not _reachable():
    pytest.skip("Supabase local no disponible (definir SUPABASE_URL/ANON_KEY/SERVICE_ROLE_KEY)",
                allow_module_level=True)

PASSWORD = "Integracion-123"
TEXTO = "Se prohíben las mascotas de más de diez kilos en áreas comunes. " * 30


class CitingLLM(LLMProvider):
    """Cita siempre el primer fragmento recibido; cuenta cuántas veces fue invocado."""

    def __init__(self):
        self.calls = 0

    async def generate_text(self, system, user, *, max_tokens, effort):
        return LLMResult("pregunta", "fake")

    async def generate_structured(self, system, user, schema, *, max_tokens, effort):
        self.calls += 1
        data = {"respuesta": "Según la documentación [F1].", "cobertura": "completa", "interpretaciones": [],
                "citas": [{"fragmento_id": "F1", "cita_textual": ""}]}
        return LLMResult(json.dumps(data), "fake", {}, data=data)


def signup(label: str) -> dict:
    email = f"{label}.{uuid.uuid4().hex[:8]}@example.test"
    r = httpx.post(f"{URL}/auth/v1/signup", headers={"apikey": ANON},
                   json={"email": email, "password": PASSWORD, "data": {"full_name": label}}, timeout=10)
    assert r.status_code == 200 and r.json().get("access_token"), r.text
    return {"email": email, "headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


@pytest.fixture(scope="module")
def llm():
    return CitingLLM()


@pytest.fixture(scope="module")
def client(llm):
    settings = Settings(
        supabase_url=URL, supabase_anon_key=ANON, supabase_service_role_key=SERVICE,
        supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET") or None,
        embedding_provider="fake", ingestion_enabled=True, chat_rate_limit_per_minute=1000, _env_file=None)
    app = create_app(settings, Container(settings, embeddings=FakeEmbeddingProvider(), llm=llm))
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def world(client):
    a, b, c = signup("admin"), signup("lector"), signup("ajeno")
    building = client.post("/api/v1/buildings", headers=a["headers"], json={
        "nombre": "Edificio Integración", "direccion": "Calle 123", "localidad": "CABA",
        "provincia": "Buenos Aires"})
    assert building.status_code == 201, building.text
    other = client.post("/api/v1/buildings", headers=c["headers"], json={
        "nombre": "Edificio Ajeno", "direccion": "Calle 999", "localidad": "Rosario", "provincia": "Santa Fe"})
    assert other.status_code == 201, other.text
    return {"a": a, "b": b, "c": c, "bid": building.json()["id"], "other_bid": other.json()["id"]}


def upload(client, headers, bid, name="reglamento.docx", text=TEXTO):
    data = make_docx([("Reglamento", "Heading 1"), (text, None)])
    return client.post(f"/api/v1/buildings/{bid}/documents", headers=headers, data={"categoria": "reglamento"},
                       files={"file": (name, io.BytesIO(data), "application/octet-stream")})


def wait_processed(client, headers, bid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        docs = client.get(f"/api/v1/buildings/{bid}/documents", headers=headers).json()
        if docs and all(d["status"] in ("procesado", "error") for d in docs):
            return docs
        time.sleep(1)
    pytest.fail("la ingesta no terminó a tiempo")


def test_aislamiento_de_edificios(client, world):
    b, bid = world["b"]["headers"], world["bid"]
    assert client.get("/api/v1/buildings", headers=b).json() == []
    assert client.get(f"/api/v1/buildings/{bid}", headers=b).status_code == 404
    assert client.get(f"/api/v1/buildings/{bid}/documents", headers=b).status_code == 404
    assert upload(client, b, bid).status_code == 404
    assert client.post("/api/v1/conversations", headers=b, json={"building_id": bid}).status_code == 404
    edit = {"nombre": "Hack", "direccion": "Calle x", "localidad": "xx", "provincia": "xx"}
    assert client.put(f"/api/v1/buildings/{bid}", headers=b, json=edit).status_code == 404


def test_roles_y_permisos(client, world):
    a, b, bid = world["a"], world["b"], world["bid"]
    r = client.put(f"/api/v1/buildings/{bid}/members", headers=a["headers"],
                   json={"email": b["email"], "rol": "lector"})
    assert r.status_code == 200 and r.json()["rol"] == "lector"
    assert client.get(f"/api/v1/buildings/{bid}", headers=b["headers"]).json()["rol"] == "lector"
    assert upload(client, b["headers"], bid).status_code == 403
    assert client.delete(f"/api/v1/buildings/{bid}", headers=b["headers"]).status_code == 403
    assert client.put(f"/api/v1/buildings/{bid}/members", headers=b["headers"],
                      json={"email": a["email"], "rol": "lector"}).status_code == 403
    members = client.get(f"/api/v1/buildings/{bid}/members", headers=a["headers"]).json()
    admin_id = next(m["user_id"] for m in members if m["rol"] == "administrador")
    # el edificio no puede quedar sin administrador
    assert client.delete(f"/api/v1/buildings/{bid}/members/{admin_id}", headers=a["headers"]).status_code == 409


def test_ingesta_busqueda_y_citas(client, world, llm):
    a, bid = world["a"]["headers"], world["bid"]
    r = upload(client, a, bid)
    assert r.status_code == 202, r.text
    assert upload(client, a, bid).status_code == 409  # mismo hash en el mismo edificio
    docs = wait_processed(client, a, bid)
    assert docs[0]["status"] == "procesado", docs[0].get("error_message")
    assert docs[0]["chunk_count"] >= 1

    conv = client.post("/api/v1/conversations", headers=a, json={"building_id": bid}).json()
    ex = client.post(f"/api/v1/conversations/{conv['id']}/messages", headers=a,
                     json={"content": "mascotas de más de diez kilos áreas comunes"})
    assert ex.status_code == 201, ex.text
    reply = ex.json()["assistant_message"]
    assert reply["sources"] and reply["sources"][0]["document_id"] == docs[0]["id"]
    assert llm.calls >= 1
    history = client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=a).json()
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_el_asistente_no_usa_documentos_de_otro_edificio(client, world, llm):
    c, other = world["c"]["headers"], world["other_bid"]
    before = llm.calls
    conv = client.post("/api/v1/conversations", headers=c, json={"building_id": other}).json()
    ex = client.post(f"/api/v1/conversations/{conv['id']}/messages", headers=c,
                     json={"content": "mascotas de más de diez kilos áreas comunes"})
    assert ex.status_code == 201, ex.text
    reply = ex.json()["assistant_message"]
    assert reply["sources"] == [] and reply["metadata"]["cobertura"] == "sin_informacion"
    assert llm.calls == before  # sin fragmentos propios no se invoca a Claude


def test_conversaciones_son_privadas(client, world):
    a, b = world["a"]["headers"], world["b"]["headers"]
    conv = client.post("/api/v1/conversations", headers=a, json={"building_id": world["bid"]}).json()
    assert client.get(f"/api/v1/conversations/{conv['id']}", headers=b).status_code == 404
    assert client.post(f"/api/v1/conversations/{conv['id']}/messages", headers=b,
                       json={"content": "hola"}).status_code == 404


def test_eliminar_documento(client, world):
    a, bid = world["a"]["headers"], world["bid"]
    doc = client.get(f"/api/v1/buildings/{bid}/documents", headers=a).json()[0]
    assert client.delete(f"/api/v1/documents/{doc['id']}", headers=a).status_code == 204
    assert client.get(f"/api/v1/documents/{doc['id']}", headers=a).status_code == 404


def test_token_invalido(client):
    assert client.get("/api/v1/buildings", headers={"Authorization": "Bearer basura"}).status_code == 401
