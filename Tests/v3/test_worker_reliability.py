"""Worker, outbox, reconciler and protected artifact tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from webauto.runtime.artifact_store import SecureArtifactStore
from webauto.runtime.reliability import InMemoryIdempotencyStore
from webauto.runtime.worker import (
    OutboxDispatcher,
    QueueMessage,
    Reconciler,
    RunControlInbox,
    WorkerRunner,
)


class FakeQueue:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.published = []
        self.acked = []

    async def consume(self):
        return self.messages.pop(0) if self.messages else None

    async def publish(self, topic, payload):
        self.published.append((topic, payload))
        return "message-1"

    async def ack(self, message):
        self.acked.append(message.id)


@pytest.mark.asyncio
async def test_worker_acks_success_and_deduplicates_job() -> None:
    message = QueueMessage(id="m1", job_id="job-1", payload={"value": 2})
    queue = FakeQueue([message, message])
    calls = []

    async def handler(job):
        calls.append(job.job_id)
        return {"result": job.payload["value"] * 2}

    worker = WorkerRunner("worker-1", queue, handler)
    assert await worker.run_once()
    assert await worker.run_once()
    assert calls == ["job-1"]
    assert queue.acked == ["m1", "m1"]


@pytest.mark.asyncio
async def test_worker_does_not_ack_failed_job() -> None:
    message = QueueMessage(id="m1", job_id="job-1", payload={})
    queue = FakeQueue([message])

    async def handler(job):
        raise RuntimeError("failed")

    worker = WorkerRunner("worker-1", queue, handler)
    assert not await worker.run_once()
    assert queue.acked == []


class FakeOutbox:
    def __init__(self):
        self.events = [{"id": "e1", "event_type": "run.ready", "payload": {"run_id": "r1"}}]
        self.published = []

    async def pending(self, limit):
        return self.events[:limit]

    async def mark_published(self, event_id):
        self.published.append(event_id)

    async def mark_failed(self, event_id, error):
        raise AssertionError(error)


@pytest.mark.asyncio
async def test_outbox_dispatcher_publishes_then_marks_delivered() -> None:
    outbox = FakeOutbox()
    queue = FakeQueue()
    dispatched = await OutboxDispatcher(outbox, queue).dispatch_batch()
    assert dispatched == 1
    assert queue.published == [("run.ready", {"run_id": "r1"})]
    assert outbox.published == ["e1"]


@pytest.mark.asyncio
async def test_reconciler_rebuilds_missing_redis_commands_from_durable_runs() -> None:
    queue = FakeQueue()

    async def durable_ready_runs():
        return ({"run_id": "r1", "job_id": "j1"}, {"run_id": "r2", "job_id": "j2"})

    count = await Reconciler(queue, durable_ready_runs).rebuild_commands()
    assert count == 2
    assert [payload["run_id"] for _, payload in queue.published] == ["r1", "r2"]


@pytest.mark.asyncio
async def test_artifact_store_redacts_checksums_authorizes_and_expires(tmp_path: Path) -> None:
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    store = SecureArtifactStore(tmp_path, clock=lambda: now)
    record = await store.put(
        owner_id="user-1",
        content=b"token=secret-value",
        media_type="text/plain",
        retention=timedelta(hours=1),
        redact=lambda value: value.replace(b"secret-value", b"<redacted>"),
    )
    assert record.sha256
    assert await store.get(record.id, owner_id="user-1") == b"token=<redacted>"
    with pytest.raises(PermissionError):
        await store.get(record.id, owner_id="user-2")

    store._clock = lambda: now + timedelta(hours=2)
    assert await store.purge_expired() == 1


def test_user_interjection_can_pause_modify_and_cancel() -> None:
    inbox = RunControlInbox()
    inbox.pause("run-1")
    inbox.modify_goal("run-1", {"max_price": 200})
    inbox.cancel("run-1")
    commands = inbox.drain("run-1")
    assert [command.kind for command in commands] == ["pause", "modify_goal", "cancel"]


@pytest.mark.asyncio
async def test_worker_restart_uses_durable_idempotency_result() -> None:
    message = QueueMessage(id="m1", job_id="job-restart", payload={"value": 2})
    store = InMemoryIdempotencyStore()
    calls = []

    async def handler(job):
        calls.append(job.job_id)
        return {"result": 4}

    first_queue = FakeQueue([message])
    assert await WorkerRunner("worker-1", first_queue, handler, idempotency=store).run_once()
    restarted_queue = FakeQueue([message])
    assert await WorkerRunner("worker-2", restarted_queue, handler, idempotency=store).run_once()
    assert calls == ["job-restart"]
    assert restarted_queue.acked == ["m1"]


@pytest.mark.asyncio
async def test_failed_worker_abandons_claim_so_redelivery_can_retry() -> None:
    message = QueueMessage(id="m1", job_id="job-retry", payload={})
    store = InMemoryIdempotencyStore()

    async def fails(job):
        raise RuntimeError("transient")

    assert not await WorkerRunner(
        "worker-1", FakeQueue([message]), fails, idempotency=store
    ).run_once()

    async def succeeds(job):
        return {"status": "ok"}

    queue = FakeQueue([message])
    assert await WorkerRunner("worker-2", queue, succeeds, idempotency=store).run_once()
    assert queue.acked == ["m1"]
