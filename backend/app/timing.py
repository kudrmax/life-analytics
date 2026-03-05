import logging
import time
from typing import Any, Callable, Awaitable

logger = logging.getLogger("app.db")

SLOW_QUERY_MS = 200


async def timed_fetch(
    label: str,
    method: Callable[..., Awaitable[Any]],
    query: str,
    *args,
) -> Any:
    t0 = time.perf_counter()
    result = await method(query, *args)
    ms = (time.perf_counter() - t0) * 1000
    if ms > SLOW_QUERY_MS:
        logger.warning("SLOW [%s] %.0fms", label, ms)
    else:
        logger.debug("[%s] %.0fms", label, ms)
    return result


class QueryTimer:
    def __init__(self, route_label: str):
        self._label = route_label
        self._t0 = time.perf_counter()
        self._marks: list[tuple[str, float]] = []

    def mark(self, name: str) -> None:
        self._marks.append((name, time.perf_counter()))

    def log(self) -> None:
        total = (time.perf_counter() - self._t0) * 1000
        parts = []
        prev = self._t0
        for name, t in self._marks:
            parts.append(f"{name}={((t - prev) * 1000):.0f}ms")
            prev = t
        logger.info("[%s] total=%.0fms  %s", self._label, total, "  ".join(parts))
