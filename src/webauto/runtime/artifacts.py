"""Content-addressed local artifact storage for screenshots and diagnostics."""

from __future__ import annotations

import hashlib
from pathlib import Path


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def put(self, content: bytes, *, extension: str) -> str:
        artifact_id = hashlib.sha256(content).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{artifact_id}.{extension.lstrip('.')}"
        if not path.exists():
            path.write_bytes(content)
        return artifact_id
