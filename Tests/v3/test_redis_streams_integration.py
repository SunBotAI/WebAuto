"""Real local Redis Streams integration test."""

from uuid import uuid4

import pytest

from webauto.runtime.redis_streams import RedisStreams


@pytest.mark.asyncio
async def test_real_redis_stream_publish_consume_ack() -> None:
    redis = pytest.importorskip("redis.asyncio")
    client = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    try:
        try:
            await client.ping()
        except Exception as exc:  # noqa: BLE001 - optional Redis transport boundary
            pytest.skip(f"local Redis unavailable: {type(exc).__name__}")
        prefix = f"webauto-test-{uuid4().hex}"
        streams = RedisStreams(client, prefix=prefix)
        await streams.ensure_group("commands", "workers")
        message_id = await streams.publish("commands", {"job_id": "job-1"})
        messages = await streams.consume(
            "commands", group="workers", consumer="worker-1", count=1, block_ms=100
        )
        assert messages == ((message_id, {"job_id": "job-1"}),)
        assert await streams.ack("commands", "workers", message_id) == 1
    finally:
        keys = await client.keys("webauto-test-*")
        if keys:
            await client.delete(*keys)
        await client.aclose()
