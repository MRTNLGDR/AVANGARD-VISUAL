from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: str, detail: Any) -> None:
        payload = {
            "event": event,
            "detail": detail,
            "created_at": datetime.now(UTC).isoformat(),
        }
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    async def stream(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield (
                        f"event: {payload['event']}\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                except TimeoutError:
                    yield "event: keepalive\ndata: {}\n\n"
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
