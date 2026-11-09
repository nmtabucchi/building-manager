"""Único punto de acceso a la base de datos.

Invoca stored procedures (funciones `sp_*`) mediante Supabase RPC (PostgREST):
    POST {SUPABASE_URL}/rest/v1/rpc/<nombre>   con parámetros JSON con nombre.

No existe aquí (ni en ninguna otra clase) SQL embebido ni concatenación de
valores: los parámetros viajan como JSON y el nombre del procedimiento se valida
contra una lista blanca de formato.
"""
import asyncio
import logging
import re
import time
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.domain.auth import AuthContext, ServiceAuthContext, UserAuthContext
from app.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InfrastructureError,
    NotFoundError,
    PermissionDeniedError,
    PersistenceUnavailableError,
    ValidationError,
)

logger = logging.getLogger(__name__)

_SP_NAME_RE = re.compile(r"^sp_[a-z0-9_]+$")

# SQLSTATE devuelto por los SP -> excepción de dominio (ver docs/catalogo-stored-procedures.md)
_ERROR_MAP: dict[str, type[DomainError]] = {
    "BM401": AuthenticationError,
    "BM403": PermissionDeniedError,
    "BM404": NotFoundError,
    "BM409": ConflictError,
    "BM422": ValidationError,
    "42501": PermissionDeniedError,  # sin privilegio EXECUTE
}


def _serialize(value: Any) -> Any:
    """Convierte tipos Python a JSON-compatibles. Nunca arma sentencias."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


class StoredProcedureClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self._settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=settings.supabase_rest_url,
            timeout=settings.sp_timeout_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # ------------------------------------------------------------------ API
    async def call(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        auth: AuthContext,
        read_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Invoca un SP y devuelve la lista de filas. Reintenta solo si `read_only`."""
        if not _SP_NAME_RE.fullmatch(name):
            raise InfrastructureError(f"Nombre de stored procedure inválido: {name!r}")

        headers = self._headers(auth)
        payload = _serialize(params or {})
        attempts = 1 + (self._settings.sp_read_retries if read_only else 0)

        last_exc: Exception | None = None
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                response = await self._http.post(f"/rpc/{name}", json=payload, headers=headers)
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("SP %s: error de red (intento %d/%d)", name, attempt + 1, attempts)
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.2 * (2**attempt))
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000
            if response.status_code >= 500 and attempt + 1 < attempts:
                logger.warning("SP %s: HTTP %d (intento %d/%d)", name, response.status_code, attempt + 1, attempts)
                await asyncio.sleep(0.2 * (2**attempt))
                continue

            if response.is_success:
                rows = self._parse_rows(name, response)
                logger.info("SP %s ok rows=%d %.0fms", name, len(rows), elapsed_ms)
                return rows

            raise self._map_error(name, response, elapsed_ms)

        raise PersistenceUnavailableError("No se pudo contactar la base de datos") from last_exc

    async def call_one(
        self, name: str, params: dict[str, Any] | None = None, *, auth: AuthContext, read_only: bool = False
    ) -> dict[str, Any]:
        """Exige exactamente una fila."""
        rows = await self.call(name, params, auth=auth, read_only=read_only)
        if len(rows) != 1:
            raise InfrastructureError(f"{name} devolvió {len(rows)} filas; se esperaba 1")
        return rows[0]

    async def call_optional(
        self, name: str, params: dict[str, Any] | None = None, *, auth: AuthContext, read_only: bool = False
    ) -> dict[str, Any] | None:
        """0 o 1 fila."""
        rows = await self.call(name, params, auth=auth, read_only=read_only)
        if len(rows) > 1:
            raise InfrastructureError(f"{name} devolvió {len(rows)} filas; se esperaba 0 o 1")
        return rows[0] if rows else None

    # ------------------------------------------------------------ internals
    def _headers(self, auth: AuthContext) -> dict[str, str]:
        anon = self._settings.supabase_anon_key.get_secret_value()
        if isinstance(auth, UserAuthContext):
            return {"apikey": anon, "Authorization": f"Bearer {auth.jwt}", "Content-Type": "application/json"}
        if isinstance(auth, ServiceAuthContext):
            key = self._settings.supabase_service_role_key
            if key is None:
                raise InfrastructureError("SUPABASE_SERVICE_ROLE_KEY no está configurada")
            secret = key.get_secret_value()
            return {"apikey": secret, "Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
        raise InfrastructureError("Contexto de autenticación no soportado")

    @staticmethod
    def _parse_rows(name: str, response: httpx.Response) -> list[dict[str, Any]]:
        try:
            data = response.json()
        except ValueError as exc:
            raise InfrastructureError(f"{name}: respuesta no es JSON") from exc
        if data is None:
            return []
        if not isinstance(data, list):
            raise InfrastructureError(f"{name}: se esperaba una lista de filas")
        return data

    @staticmethod
    def _map_error(name: str, response: httpx.Response, elapsed_ms: float) -> DomainError:
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code", "")) if isinstance(body, dict) else ""
        message = str(body.get("message", "")) if isinstance(body, dict) else ""
        detail = body.get("details") if isinstance(body, dict) else None
        detail = str(detail) if detail else None

        logger.warning("SP %s error http=%d code=%s %.0fms", name, response.status_code, code, elapsed_ms)

        exc_cls = _ERROR_MAP.get(code)
        if exc_cls is not None:
            return exc_cls(message or "Error de negocio", detail)
        if response.status_code in (401, 403) and not code.startswith("PGRST"):
            return PermissionDeniedError(message or "Acceso denegado", detail)
        if response.status_code == 401 or code in ("PGRST301", "PGRST303"):
            return AuthenticationError("Token inválido o expirado")
        if code == "PGRST202":
            return InfrastructureError(f"Stored procedure inexistente o firma distinta: {name}")
        if response.status_code >= 500 or response.status_code == 503:
            return PersistenceUnavailableError("La base de datos no está disponible")
        return InfrastructureError(f"Error inesperado en {name}", f"{code} {message}".strip())
