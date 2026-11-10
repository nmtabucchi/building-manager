"""Controles de seguridad transversales."""
import re
from datetime import datetime, UTC
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.container import Container
from app.main import create_app
from tests.unit.test_api import FakeSP, token

ROOT = Path(__file__).resolve().parents[3]
UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, Container(settings, sp_client=FakeSP()))) as c:
        yield c


def _status(client, tok):
    return client.get("/api/v1/buildings", headers={"Authorization": f"Bearer {tok}"}).status_code


def test_jwt_alg_none_y_emisor_ajeno_son_rechazados(client, settings):
    exp = int(datetime.now(UTC).timestamp()) + 3600
    claims = {"sub": UID, "aud": "authenticated", "iss": settings.supabase_issuer, "exp": exp}
    assert _status(client, jwt.encode(claims, None, algorithm="none")) == 401
    assert _status(client, token(settings, iss="https://evil.example/auth/v1")) == 401
    assert _status(client, token(settings, sub="no-es-uuid")) == 401
    sin_exp = {k: v for k, v in claims.items() if k != "exp"}
    assert _status(client, jwt.encode(sin_exp, settings.supabase_jwt_secret.get_secret_value(), algorithm="HS256")) == 401


def test_auth_context_no_expone_el_jwt_en_logs():
    from uuid import UUID

    from app.domain.auth import UserAuthContext
    ctx = UserAuthContext(user_id=UUID(UID), email="a@b.c", jwt="secreto-jwt")
    assert "secreto-jwt" not in repr(ctx) and "secreto-jwt" not in str(ctx)


def test_cors_solo_permite_el_origen_configurado(client):
    ok = client.options("/api/v1/buildings", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/v1/buildings", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


def test_el_frontend_no_contiene_claves_privadas():
    """Ningún archivo fuente del frontend referencia claves privadas (solo variables NEXT_PUBLIC_*)."""
    pattern = re.compile(r"service_role|SERVICE_ROLE|ANTHROPIC|EMBEDDING_API_KEY|sk-ant-", re.IGNORECASE)
    hits = []
    for path in (ROOT / "frontend").rglob("*"):
        if path.is_file() and path.suffix in {".js", ".mjs", ".json", ".css", ".md"} and not any(
                part in {"node_modules", ".next"} for part in path.parts) and path.name != "package-lock.json":
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == [] or hits == ["frontend/.env.example"], hits  # .env.example solo lo advierte en un comentario


def test_variables_de_entorno_del_frontend_son_solo_publicas():
    env_vars = set()
    for path in (ROOT / "frontend").rglob("*.js"):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        env_vars |= set(re.findall(r"process\.env\.([A-Z0-9_]+)", path.read_text(encoding="utf-8")))
    assert env_vars and all(v.startswith("NEXT_PUBLIC_") or v == "NODE_ENV" for v in env_vars), env_vars


def test_archivos_env_reales_estan_ignorados_y_los_ejemplos_no_tienen_secretos():
    for gi in (ROOT / "backend" / ".gitignore", ROOT / "frontend" / ".gitignore"):
        assert re.search(r"^\.env$", gi.read_text(encoding="utf-8"), re.MULTILINE), gi
    for example in (ROOT / "backend" / ".env.example", ROOT / "frontend" / ".env.example"):
        for line in example.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                value = line.split("=", 1)[1].split("#")[0].strip()
                assert not re.search(r"eyJ[A-Za-z0-9_-]{20,}|sk-ant-|sb_secret_", value), line


def test_no_hay_credenciales_hardcodeadas_en_app():
    pattern = re.compile(r"sk-ant-[A-Za-z0-9]|eyJ[A-Za-z0-9_-]{30,}|sb_secret_|pa-[A-Za-z0-9]{20,}")
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path
