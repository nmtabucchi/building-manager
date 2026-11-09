"""Cola de ingesta. Interfaz + implementación en memoria (MVP); reemplazable por una cola real."""
import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from uuid import UUID

logger = logging.getLogger(__name__)

Handler = Callable[[UUID], Awaitable[None]]


class IngestionQueue(ABC):
    @abstractmethod
    async def enqueue(self, document_id: UUID) -> None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...


class InMemoryIngestionQueue(IngestionQueue):
    def __init__(self, handler: Handler, workers: int = 1):
        self._handler = handler
        self._n = workers
        self._queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._pending: set[UUID] = set()  # evita encolar dos veces el mismo documento
        self._tasks: list[asyncio.Task] = []

    async def enqueue(self, document_id: UUID) -> None:
        if document_id in self._pending:
            return
        self._pending.add(document_id)
        await self._queue.put(document_id)

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._worker(i)) for i in range(self._n)]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def join(self) -> None:
        """Espera a que se vacíe la cola (tests)."""
        await self._queue.join()

    async def _worker(self, n: int) -> None:
        while True:
            document_id = await self._queue.get()
            try:
                await self._handler(document_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker %d: fallo no controlado con %s", n, document_id)
            finally:
                self._pending.discard(document_id)
                self._queue.task_done()
