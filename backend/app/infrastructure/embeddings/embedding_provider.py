"""Proveedores de embeddings, desacoplados del proveedor de LLM."""
import asyncio
import hashlib
import logging
import math
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings
from app.domain.exceptions import InfrastructureError, PersistenceUnavailableError

logger = logging.getLogger(__name__)

DB_EMBEDDING_DIM = 1024  # debe coincidir con document_chunks.embedding vector(1024)


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...


class FakeEmbeddingProvider(EmbeddingProvider):
    """Determinístico (hash de palabras -> vector normalizado). Solo desarrollo y tests."""

    def __init__(self, dimension: int = DB_EMBEDDING_DIM):
        self._dim = dimension

    @property
    def model_name(self) -> str:
        return "fake-hash"

    @property
    def dimension(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in text.lower().split():
            h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
            vec[h % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI (API REST). Distingue input_type 'document' y 'query'."""

    URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str | None, model: str, dimension: int = DB_EMBEDDING_DIM,
                 http: httpx.AsyncClient | None = None, retries: int = 3):
        self._key, self._model, self._dim = api_key, model, dimension
        self._http = http or httpx.AsyncClient(timeout=60)
        self._retries = retries

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        if not self._key:
            raise InfrastructureError("EMBEDDING_API_KEY no está configurada")
        body = {"input": texts, "model": self._model, "input_type": input_type, "output_dimension": self._dim}
        headers = {"Authorization": f"Bearer {self._key}"}
        for attempt in range(self._retries):
            try:
                r = await self._http.post(self.URL, json=body, headers=headers)
            except httpx.TransportError:
                r = None
            if r is not None and r.is_success:
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            retryable = r is None or r.status_code == 429 or r.status_code >= 500
            if not retryable:
                raise InfrastructureError("El proveedor de embeddings rechazó la solicitud", f"HTTP {r.status_code}")
            logger.warning("Embeddings: reintento %d/%d", attempt + 1, self._retries)
            await asyncio.sleep(1.0 * 2**attempt)
        raise PersistenceUnavailableError("El proveedor de embeddings no está disponible")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, "document")

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "query"))[0]


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_dimension != DB_EMBEDDING_DIM:
        raise InfrastructureError(
            f"EMBEDDING_DIMENSION={settings.embedding_dimension} no coincide con vector({DB_EMBEDDING_DIM}) de la base")
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider()
    if settings.embedding_provider == "voyage":
        key = settings.embedding_api_key.get_secret_value() if settings.embedding_api_key else None
        return VoyageEmbeddingProvider(key, settings.embedding_model, settings.embedding_dimension)
    raise InfrastructureError(f"EMBEDDING_PROVIDER no soportado: {settings.embedding_provider}")
