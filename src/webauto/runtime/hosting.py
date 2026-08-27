"""Remote-dedicated environments, tenant isolation, ACK ledger and backup recovery."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from webauto.domain import Placement
from webauto.runtime.browser import InMemoryLeaseManager, LeaseConflict, ProfileLease


@dataclass(frozen=True, slots=True)
class RemoteAllocation:
    id: str
    tenant_id: str
    profile_id: str
    node_id: str
    volume: Path
    fencing_token: int


class RemoteDedicatedManager:
    def __init__(self, volumes_root: Path) -> None:
        self._root = volumes_root
        self._leases = InMemoryLeaseManager()
        self._profile_tenants: dict[str, str] = {}
        self._active: dict[str, ProfileLease] = {}

    async def allocate(self, tenant_id: str, profile_id: str, node_id: str) -> RemoteAllocation:
        bound_tenant = self._profile_tenants.get(profile_id)
        if bound_tenant is not None and bound_tenant != tenant_id:
            raise RuntimeError("profile belongs to a different tenant")
        try:
            lease = await self._leases.acquire(
                profile_id, node_id, Placement.REMOTE_DEDICATED, ttl_seconds=300
            )
        except LeaseConflict as exc:
            raise RuntimeError("profile already has a writer") from exc
        self._profile_tenants[profile_id] = tenant_id
        tenant_key = hashlib.sha256(tenant_id.encode()).hexdigest()[:16]
        profile_key = hashlib.sha256(profile_id.encode()).hexdigest()[:16]
        volume = (self._root / tenant_key / profile_key).resolve()
        volume.mkdir(parents=True, exist_ok=True)
        allocation = RemoteAllocation(
            str(uuid4()), tenant_id, profile_id, node_id, volume, lease.fencing_token
        )
        self._active[allocation.id] = lease
        return allocation

    async def release(self, allocation: RemoteAllocation) -> None:
        lease = self._active.pop(allocation.id)
        await self._leases.release(lease)


class TenantIsolationRegistry:
    _kinds: ClassVar[set[str]] = {
        "profiles",
        "cookies",
        "artifacts",
        "memory",
        "runs",
        "logs",
    }

    def __init__(self) -> None:
        self._owners: dict[tuple[str, str], str] = {}

    def bind(self, tenant_id: str, kind: str, resource_id: str) -> None:
        if kind not in self._kinds:
            raise ValueError("unsupported sensitive resource kind")
        key = (kind, resource_id)
        existing = self._owners.get(key)
        if existing is not None and existing != tenant_id:
            raise PermissionError("resource already belongs to another tenant")
        self._owners[key] = tenant_id

    def authorize(self, tenant_id: str, kind: str, resource_id: str) -> bool:
        return self._owners.get((kind, resource_id)) == tenant_id


@dataclass(frozen=True, slots=True)
class PendingCommand:
    id: str
    device_id: str
    payload: dict[str, Any]
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CommandLedger:
    def __init__(self) -> None:
        self._commands: dict[str, PendingCommand] = {}
        self._acked: set[str] = set()

    def issue(self, device_id: str, payload: dict[str, Any]) -> PendingCommand:
        command = PendingCommand(str(uuid4()), device_id, dict(payload))
        self._commands[command.id] = command
        return command

    def ack(self, device_id: str, command_id: str) -> None:
        command = self._commands[command_id]
        if command.device_id != device_id:
            raise PermissionError("command ACK device mismatch")
        self._acked.add(command_id)

    def pending(self, device_id: str) -> tuple[PendingCommand, ...]:
        return tuple(
            command
            for command in self._commands.values()
            if command.device_id == device_id and command.id not in self._acked
        )


@dataclass(slots=True)
class BackupManifest:
    id: str
    source: Path
    files: dict[str, Path]
    checksums: dict[str, str]
    created_at: datetime


class BackupManager:
    def __init__(self, root: Path) -> None:
        self._root = root

    def create(self, source: Path) -> BackupManifest:
        if not source.is_dir():
            raise FileNotFoundError(source)
        backup_id = str(uuid4())
        destination = self._root / backup_id
        destination.mkdir(parents=True, exist_ok=False)
        files: dict[str, Path] = {}
        checksums: dict[str, str] = {}
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            relative = path.relative_to(source).as_posix()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            files[relative] = target
            checksums[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        return BackupManifest(
            backup_id, source.resolve(), files, checksums, datetime.now(timezone.utc)
        )

    def verify(self, manifest: BackupManifest) -> bool:
        return all(
            path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == manifest.checksums[name]
            for name, path in manifest.files.items()
        )

    def restore(self, manifest: BackupManifest, target: Path) -> None:
        if not self.verify(manifest):
            raise OSError("backup checksum verification failed")
        if target.exists() and any(target.iterdir()):
            raise FileExistsError("restore target must be empty")
        target.mkdir(parents=True, exist_ok=True)
        for relative, source in manifest.files.items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
