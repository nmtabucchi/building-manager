"""Proveedores de embeddings, desacoplados del proveedor de LLM."""
import asyncio
import hashlib
import logging
import math
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import Settings
from app.domain.exceptions import InfrastructureError, PersistenceUnavailableError

logger = logging.getLogger(__name__)

DB_EMBEDDING_DIM = 1024  # debe coincidir con document_chunks.embedding vector(1024)


def estimate_tokens(text: str) -> int:
    """Estimación conservadora (español): ~1 token cada 3 caracteres."""
    return max(1, len(text) // 3)


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


class RateThrottle:
    """Limitador cliente (ventana de 60 s) por peticiones y tokens. 0 = sin límite.

    Se comparte entre la ingesta y las consultas del chat (una sola instancia del proveedor), de modo que
    ambas respetan el mismo cupo del proveedor.
    """

    WINDOW = 60.0

    def __init__(self, rpm: int = 0, tpm: int = 0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] | None = None):
        self._rpm, self._tpm, self._clock = rpm, tpm, clock
        self._sleep = sleep or asyncio.sleep
        self._events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._rpm or self._tpm)

    async def acquire(self, tokens: int) -> None:
        if not self.enabled:
            return
        async with self._lock:
            while True:
                now = self._clock()
                while self._events and now - self._events[0][0] >= self.WINDOW:
                    self._events.popleft()
                wait = self._wait_needed(now, tokens)
                if wait <= 0:
                    self._events.append((now, tokens))
                    return
                logger.info("Embeddings: esperando %.1f s para respetar el límite del proveedor", wait)
                await self._sleep(wait)

    def _wait_needed(self, now: float, tokens: int) -> float:
        wait = 0.0
        if self._rpm and len(self._events) >= self._rpm:
            wait = self._events[0][0] + self.WINDOW - now
        if self._tpm and self._events:
            used = sum(t for _, t in self._events)
            if used + tokens > self._tpm:
                freed = 0
                for ts, t in self._events:
                    freed += t
                    if used - freed + tokens <= self._tpm:
                        wait = max(wait, ts + self.WINDOW - now)
                        break
                else:
                    wait = max(wait, self._events[-1][0] + self.WINDOW - now)
        return max(wait, 0.0)


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI (API REST). Distingue input_type 'document' y 'query'."""

    URL = "https://api.voyageai.com/v1/embeddings"
    MAX_INPUTS = 128

    def __init__(self, api_key: str | None, model: str, dimension: int = DB_EMBEDDING_DIM,
                 http: httpx.AsyncClient | None = None, retries: int = 3, rpm: int = 0, tpm: int = 0,
                 throttle: RateThrottle | None = None):
        self._key, self._model, self._dim = api_key, model, dimension
        self._http = http or httpx.AsyncClient(timeout=60)
        self._retries = retries
        self._tpm = tpm
        self._throttle = throttle or RateThrottle(rpm, tpm)

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
        tokens = sum(estimate_tokens(t) for t in texts)
        for attempt in range(self._retries):
            await self._throttle.acquire(tokens)
            try:
                r = await self._http.post(self.URL, json=body, headers=headers)
            except httpx.TransportError:
                r = None
            if r is not None and r.is_success:
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            retryable = r is None or r.status_code == 429 or r.status_code >= 500
            if not retryable:
                raise PersistenceUnavailableError(
                    "El proveedor de embeddings rechazó la solicitud (revise EMBEDDING_API_KEY)", f"HTTP {r.status_code}")
            logger.warning("Embeddings: reintento %d/%d (HTTP %s)", attempt + 1, self._retries,
                           r.status_code if r is not None else "red")
            if attempt + 1 < self._retries:
                await asyncio.sleep(self._retry_delay(r, attempt))
        raise PersistenceUnavailableError(
            "El proveedor de embeddings no está disponible o superó su límite de uso; intente en un minuto")

    @staticmethod
    def _retry_delay(r: httpx.Response | None, attempt: int) -> float:
        if r is not None and r.status_code == 429:
            try:
                return min(float(r.headers.get("retry-after", "")), 65.0)
            except ValueError:
                return 20.0 * (attempt + 1)  # cuota por minuto: esperar a que se renueve
        return 1.0 * 2**attempt

    def _split(self, texts: list[str]) -> list[list[str]]:
        """Agrupa textos para que cada petición quepa en el cupo de tokens por minuto."""
        budget = int(self._tpm * 0.7) if self._tpm else None
        groups: list[list[str]] = []
        current: list[str] = []
        used = 0
        for text in texts:
            t = estimate_tokens(text)
            if current and (len(current) >= self.MAX_INPUTS or (budget and used + t > budget)):
                groups.append(current)
                current, used = [], 0
            current.append(text)
            used += t
        if current:
            groups.append(current)
        return groups

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for group in self._split(texts):
            out.extend(await self._embed(group, "document"))
        return out

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
        return VoyageEmbeddingProvider(key, settings.embedding_model, settings.embedding_dimension,
                                       rpm=settings.embedding_max_rpm, tpm=settings.embedding_max_tpm)
    raise InfrastructureError(f"EMBEDDING_PROVIDER no soportado: {settings.embedding_provider}")
