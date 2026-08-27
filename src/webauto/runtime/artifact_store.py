"""Owner-scoped, checksummed and retention-aware artifact store."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    id: str
    owner_id: str
    media_type: str
    sha256: str
    size: int
    path: Path
    created_at: datetime
    expires_at: datetime


class SecureArtifactStore:
    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.root = root
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._records: dict[str, ArtifactRecord] = {}

    async def put(
        self,
        *,
        owner_id: str,
        content: bytes,
        media_type: str,
        retention: timedelta,
        redact: Callable[[bytes], bytes] | None = None,
    ) -> ArtifactRecord:
        if retention.total_seconds() <= 0:
            raise ValueError("artifact retention must be positive")
        protected = redact(content) if redact else content
        digest = hashlib.sha256(protected).hexdigest()
        artifact_id = str(uuid4())
        owner_root = self.root / hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]
        owner_root.mkdir(parents=True, exist_ok=True)
        path = owner_root / f"{artifact_id}.bin"
        path.write_bytes(protected)
        now = self._clock()
        record = ArtifactRecord(
            id=artifact_id,
            owner_id=owner_id,
            media_type=media_type,
            sha256=digest,
            size=len(protected),
            path=path,
            created_at=now,
            expires_at=now + retention,
        )
        self._records[artifact_id] = record
        return record

    async def get(self, artifact_id: str, *, owner_id: str) -> bytes:
        record = self._records[artifact_id]
        if record.owner_id != owner_id:
            raise PermissionError("artifact owner mismatch")
        if self._clock() >= record.expires_at:
            raise FileNotFoundError("artifact expired")
        content = record.path.read_bytes()
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise OSError("artifact checksum mismatch")
        return content

    async def purge_expired(self) -> int:
        expired = [
            record for record in self._records.values() if self._clock() >= record.expires_at
        ]
        for record in expired:
            record.path.unlink(missing_ok=True)
            del self._records[record.id]
        return len(expired)
