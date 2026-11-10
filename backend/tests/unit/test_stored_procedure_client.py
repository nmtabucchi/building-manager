import json
from datetime import date
from uuid import UUID

import httpx
import pytest
import respx

from app.domain.auth import ServiceAuthContext, UserAuthContext
from app.domain.enums import BuildingRole
from app.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    InfrastructureError,
    NotFoundError,
    PermissionDeniedError,
    PersistenceUnavailableError,
    ValidationError,
)
from app.infrastructure.database.stored_procedure_client import StoredProcedureClient

RPC = "http://supabase.test/rest/v1/rpc"
UID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def user():
    return UserAuthContext(user_id=UID, email="a@b.c", jwt="user-jwt")


@pytest.fixture
def client(settings):
    return StoredProcedureClient(settings)


@respx.mock
async def test_envia_parametros_serializados_y_jwt_del_usuario(client, user):
    route = respx.post(f"{RPC}/sp_building_obtener_por_id").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    rows = await client.call("sp_building_obtener_por_id", {
        "p_building_id": UID, "p_rol": BuildingRole.LECTOR, "p_fecha": date(2026, 1, 2)}, auth=user)
    assert rows == [{"id": 1}]
    req = route.calls[0].request
    assert json.loads(req.content) == {"p_building_id": str(UID), "p_rol": "lector", "p_fecha": "2026-01-02"}
    assert req.headers["authorization"] == "Bearer user-jwt"
    assert req.headers["apikey"] == "anon-key"


@respx.mock
async def test_service_context_usa_service_role(client):
    route = respx.post(f"{RPC}/sp_ingesta_document_obtener").mock(return_value=httpx.Response(200, json=[]))
    await client.call("sp_ingesta_document_obtener", {}, auth=ServiceAuthContext())
    assert route.calls[0].request.headers["authorization"] == "Bearer service-key"


@pytest.mark.parametrize("name", ["building; drop table x", "sp_X", "fn_algo", "sp_a/../b", ""])
async def test_rechaza_nombres_invalidos(client, user, name):
    with pytest.raises(InfrastructureError):
        await client.call(name, {}, auth=user)


@pytest.mark.parametrize("code,exc", [
    ("BM401", AuthenticationError), ("BM403", PermissionDeniedError), ("BM404", NotFoundError),
    ("BM409", ConflictError), ("BM422", ValidationError), ("42501", PermissionDeniedError),
])
@respx.mock
async def test_mapea_errores_de_negocio(client, user, code, exc):
    respx.post(f"{RPC}/sp_x").mock(return_value=httpx.Response(400, json={"code": code, "message": "msg", "details": "d"}))
    with pytest.raises(exc) as info:
        await client.call("sp_x", {}, auth=user)
    assert info.value.message == "msg"


@respx.mock
async def test_funcion_inexistente_es_error_de_infraestructura(client, user):
    respx.post(f"{RPC}/sp_x").mock(return_value=httpx.Response(404, json={"code": "PGRST202", "message": "no"}))
    with pytest.raises(InfrastructureError):
        await client.call("sp_x", {}, auth=user)


@respx.mock
async def test_jwt_expirado_en_postgrest(client, user):
    respx.post(f"{RPC}/sp_x").mock(return_value=httpx.Response(401, json={"code": "PGRST301", "message": "JWT expired"}))
    with pytest.raises(AuthenticationError):
        await client.call("sp_x", {}, auth=user)


@respx.mock
async def test_lecturas_reintentan_ante_5xx(client, user):
    route = respx.post(f"{RPC}/sp_x").mock(side_effect=[httpx.Response(503), httpx.Response(200, json=[{"a": 1}])])
    assert await client.call("sp_x", {}, auth=user, read_only=True) == [{"a": 1}]
    assert route.call_count == 2


@respx.mock
async def test_escrituras_no_reintentan(client, user):
    route = respx.post(f"{RPC}/sp_x").mock(return_value=httpx.Response(503, json={}))
    with pytest.raises(PersistenceUnavailableError):
        await client.call("sp_x", {}, auth=user)
    assert route.call_count == 1


@respx.mock
async def test_error_de_red_en_escritura(client, user):
    respx.post(f"{RPC}/sp_x").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(PersistenceUnavailableError):
        await client.call("sp_x", {}, auth=user)


@respx.mock
async def test_call_one_exige_una_fila(client, user):
    respx.post(f"{RPC}/sp_x").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(InfrastructureError):
        await client.call_one("sp_x", {}, auth=user)
    assert await client.call_optional("sp_x", {}, auth=user) is None
