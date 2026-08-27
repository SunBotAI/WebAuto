"""Reliable worker, outbox dispatch, reconciliation and run control."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class QueueMessage:
    id: str
    job_id: str
    payload: dict[str, Any]
    deadline: datetime | None = None


class WorkQueue(Protocol):
    async def consume(self) -> QueueMessage | None: ...

    async def publish(self, topic: str, payload: dict[str, Any]) -> str: ...

    async def ack(self, message: QueueMessage) -> None: ...


class IdempotencyStore(Protocol):
    async def claim(self, key: str) -> bool: ...

    async def complete(self, key: str, result: dict[str, Any]) -> None: ...

    async def result(self, key: str) -> dict[str, Any] | None: ...

    async def abandon(self, key: str) -> None: ...


JobHandler = Callable[[QueueMessage], Awaitable[dict[str, Any]]]


class WorkerRunner:
    def __init__(
        self,
        worker_id: str,
        queue: WorkQueue,
        handler: JobHandler,
        *,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self.worker_id = worker_id
        self._queue = queue
        self._handler = handler
        self._idempotency = idempotency
        self._completed: dict[str, dict[str, Any]] = {}
        self._cancelled: set[str] = set()

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)

    async def run_once(self) -> bool:
        message = await self._queue.consume()
        if message is None:
            return False
        durable_result = (
            await self._idempotency.result(message.job_id)
            if self._idempotency is not None
            else None
        )
        if message.job_id in self._completed or durable_result is not None:
            await self._queue.ack(message)
            return True
        if message.job_id in self._cancelled:
            self._completed[message.job_id] = {"status": "cancelled"}
            await self._queue.ack(message)
            return True
        if message.deadline is not None and message.deadline <= datetime.now(timezone.utc):
            self._completed[message.job_id] = {"status": "deadline_exceeded"}
            await self._queue.ack(message)
            return True
        if self._idempotency is not None and not await self._idempotency.claim(message.job_id):
            return False
        try:
            result = await self._handler(message)
        except Exception:  # noqa: BLE001 - job handler isolation boundary
            if self._idempotency is not None:
                await self._idempotency.abandon(message.job_id)
            return False
        self._completed[message.job_id] = result
        if self._idempotency is not None:
            await self._idempotency.complete(message.job_id, result)
        await self._queue.ack(message)
        return True


class OutboxStore(Protocol):
    async def pending(self, limit: int) -> list[dict[str, Any]]: ...

    async def mark_published(self, event_id: str) -> None: ...

    async def mark_failed(self, event_id: str, error: str) -> None: ...


class OutboxDispatcher:
    def __init__(self, outbox: OutboxStore, queue: WorkQueue) -> None:
        self._outbox = outbox
        self._queue = queue

    async def dispatch_batch(self, limit: int = 100) -> int:
        dispatched = 0
        for event in await self._outbox.pending(limit):
            try:
                await self._queue.publish(event["event_type"], event["payload"])
                await self._outbox.mark_published(event["id"])
                dispatched += 1
            except Exception as exc:  # noqa: BLE001 - outbox item isolation boundary
                await self._outbox.mark_failed(event["id"], type(exc).__name__)
        return dispatched


class Reconciler:
    def __init__(
        self,
        queue: WorkQueue,
        durable_ready_runs: Callable[[], Awaitable[tuple[dict[str, Any], ...]]],
    ) -> None:
        self._queue = queue
        self._durable_ready_runs = durable_ready_runs

    async def rebuild_commands(self) -> int:
        count = 0
        for run in await self._durable_ready_runs():
            await self._queue.publish("run.command", run)
            count += 1
        return count


@dataclass(frozen=True, slots=True)
class RunControlCommand:
    kind: str
    payload: dict[str, Any]


class RunControlInbox:
    def __init__(self) -> None:
        self._commands: dict[str, list[RunControlCommand]] = {}

    def _add(self, run_id: str, kind: str, payload: dict[str, Any] | None = None) -> None:
        self._commands.setdefault(run_id, []).append(RunControlCommand(kind, payload or {}))

    def pause(self, run_id: str) -> None:
        self._add(run_id, "pause")

    def resume(self, run_id: str) -> None:
        self._add(run_id, "resume")

    def cancel(self, run_id: str) -> None:
        self._add(run_id, "cancel")

    def modify_goal(self, run_id: str, changes: dict[str, Any]) -> None:
        self._add(run_id, "modify_goal", changes)

    def drain(self, run_id: str) -> tuple[RunControlCommand, ...]:
        return tuple(self._commands.pop(run_id, []))
