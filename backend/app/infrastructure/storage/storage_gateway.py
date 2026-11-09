"""Acceso a Supabase Storage (bucket privado) con service_role, solo desde el backend."""
from abc import ABC, abstractmethod
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.domain.exceptions import InfrastructureError, NotFoundError, PersistenceUnavailableError


class StorageGateway(ABC):
    @abstractmethod
    async def upload(self, path: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def download(self, path: str) -> bytes: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...

    @abstractmethod
    async def signed_url(self, path: str, expires_in: int = 300) -> str: ...


class SupabaseStorageGateway(StorageGateway):
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self._base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self._bucket = settings.supabase_storage_bucket
        self._key = settings.supabase_service_role_key
        self._http = http or httpx.AsyncClient(timeout=60)

    def _headers(self) -> dict[str, str]:
        if self._key is None:
            raise InfrastructureError("SUPABASE_SERVICE_ROLE_KEY no está configurada")
        secret = self._key.get_secret_value()
        return {"apikey": secret, "Authorization": f"Bearer {secret}"}

    def _object_url(self, path: str, prefix: str = "") -> str:
        return f"{self._base}/object/{prefix}{self._bucket}/{quote(path, safe='/')}"

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            r = await self._http.request(method, url, headers={**self._headers(), **kwargs.pop("headers", {})}, **kwargs)
        except httpx.TransportError as exc:
            raise PersistenceUnavailableError("Storage no disponible") from exc
        if r.status_code in (400, 404) and method in ("GET", "POST") and "not found" in r.text.lower():
            raise NotFoundError("Archivo no encontrado en Storage")
        if not r.is_success:
            raise PersistenceUnavailableError("Error en Storage", f"HTTP {r.status_code}")
        return r

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        await self._request("POST", self._object_url(path), content=data,
                            headers={"Content-Type": content_type, "x-upsert": "false"})

    async def download(self, path: str) -> bytes:
        return (await self._request("GET", self._object_url(path, "authenticated/"))).content

    async def delete(self, path: str) -> None:
        await self._request("DELETE", self._object_url(path))

    async def signed_url(self, path: str, expires_in: int = 300) -> str:
        r = await self._request("POST", f"{self._base}/object/sign/{self._bucket}/{quote(path, safe='/')}",
                                json={"expiresIn": expires_in})
        return self._base + r.json()["signedURL"]
