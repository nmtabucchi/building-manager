"""Límite de frecuencia en memoria por usuario (ventana deslizante). Protege el costo de Claude."""
import time
from collections import defaultdict, deque
from collections.abc import Callable
from uuid import UUID

from app.domain.exceptions import RateLimitError


class SlidingWindowRateLimiter:
    def __init__(self, max_calls: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self._max, self._window, self._clock = max_calls, window_seconds, clock
        self._calls: dict[UUID, deque[float]] = defaultdict(deque)

    def check(self, user_id: UUID) -> None:
        now = self._clock()
        calls = self._calls[user_id]
        while calls and now - calls[0] >= self._window:
            calls.popleft()
        if len(calls) >= self._max:
            raise RateLimitError("Demasiadas consultas; espere un momento e intente de nuevo")
        calls.append(now)
