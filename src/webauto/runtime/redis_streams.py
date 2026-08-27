"""Redis Streams adapter for commands, events, approvals and node messages."""

from __future__ import annotations

import json
from typing import Any


class RedisStreams:
    def __init__(self, client: Any, *, prefix: str = "webauto") -> None:
        self._client = client
        self._prefix = prefix

    def key(self, stream: str) -> str:
        return f"{self._prefix}:{stream}"

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._client.xgroup_create(self.key(stream), group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        encoded = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in payload.items()
        }
        return await self._client.xadd(self.key(stream), encoded)

    async def consume(
        self,
        stream: str,
        *,
        group: str,
        consumer: str,
        count: int = 1,
        block_ms: int = 1000,
    ) -> tuple[tuple[str, dict[str, str]], ...]:
        records = await self._client.xreadgroup(
            group,
            consumer,
            {self.key(stream): ">"},
            count=count,
            block=block_ms,
        )
        messages: list[tuple[str, dict[str, str]]] = []
        for _, stream_messages in records:
            messages.extend((message_id, fields) for message_id, fields in stream_messages)
        return tuple(messages)

    async def ack(self, stream: str, group: str, *message_ids: str) -> int:
        return int(await self._client.xack(self.key(stream), group, *message_ids))
