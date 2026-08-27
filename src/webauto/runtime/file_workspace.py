"""Run-isolated user file inbox, grants and inert download inventory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class FileWorkspaceViolation(RuntimeError):
    """A file operation escaped the explicit local user/run grant."""


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ALLOWED_TYPES = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "text/plain", "application/csv"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


@dataclass(frozen=True, slots=True)
class UserFileRecord:
    id: str
    owner_key: str
    filename: str
    media_type: str
    size: int
    sha256: str
    created_at: str
    path: Path

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "media_type": self.media_type,
            "size": self.size,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class RunFileGrant:
    file_id: str
    run_id: str
    filename: str
    sha256: str
    path: Path

    def public(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "run_id": self.run_id,
            "filename": self.filename,
            "sha256": self.sha256,
        }


class RunFileWorkspace:
    """Persist user-originated files without granting broad filesystem access."""

    def __init__(
        self,
        root: Path,
        downloads_root: Path,
        *,
        max_upload_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        self.root = root.resolve()
        self.downloads_root = downloads_root.resolve()
        self.max_upload_bytes = max_upload_bytes

    def add_user_file(
        self,
        *,
        owner_id: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> UserFileRecord:
        safe_name = self._validate_file(filename, media_type, content)
        owner_key = self._owner_key(owner_id)
        file_id = str(uuid4())
        owner_root = self._inside(self.root, "inbox", owner_key)
        owner_root.mkdir(parents=True, exist_ok=True)
        extension = Path(safe_name).suffix.lower()
        path = self._inside(owner_root, file_id + extension)
        temporary = self._inside(owner_root, file_id + ".part")
        temporary.write_bytes(content)
        os.replace(temporary, path)
        record = UserFileRecord(
            id=file_id,
            owner_key=owner_key,
            filename=safe_name,
            media_type=media_type.lower().strip(),
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=datetime.now(timezone.utc).isoformat(),
            path=path,
        )
        self._write_manifest(record)
        return record

    def list_user_files(self, *, owner_id: str) -> tuple[UserFileRecord, ...]:
        owner_root = self._inside(self.root, "inbox", self._owner_key(owner_id))
        if not owner_root.exists():
            return ()
        records = [self._read_manifest(path) for path in owner_root.glob("*.json")]
        return tuple(sorted(records, key=lambda item: item.created_at, reverse=True))

    def get_user_file(self, file_id: str, *, owner_id: str) -> UserFileRecord:
        self._validate_id("file_id", file_id)
        owner_root = self._inside(self.root, "inbox", self._owner_key(owner_id))
        manifest = self._inside(owner_root, file_id + ".json")
        if not manifest.is_file() or manifest.is_symlink():
            raise FileNotFoundError("approved user file was not found")
        record = self._read_manifest(manifest)
        if record.owner_key != self._owner_key(owner_id):
            raise PermissionError("user file owner mismatch")
        try:
            record.path.relative_to(owner_root.resolve())
        except ValueError as exc:
            raise FileWorkspaceViolation("user file path escapes its owner inbox") from exc
        if not record.path.is_file() or record.path.is_symlink():
            raise FileNotFoundError("approved user file content was not found")
        content = record.path.read_bytes()
        if len(content) != record.size or hashlib.sha256(content).hexdigest() != record.sha256:
            raise OSError("approved user file checksum mismatch")
        return record

    def authorize_for_run(
        self,
        *,
        owner_id: str,
        file_id: str,
        run_id: str,
    ) -> RunFileGrant:
        self._validate_id("run_id", run_id)
        record = self.get_user_file(file_id, owner_id=owner_id)
        run_root = self._inside(self.root, "runs", run_id, "uploads")
        run_root.mkdir(parents=True, exist_ok=True)
        destination = self._inside(run_root, record.id + Path(record.filename).suffix.lower())
        temporary = self._inside(run_root, record.id + ".part")
        shutil.copyfile(record.path, temporary)
        os.replace(temporary, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != record.sha256:
            destination.unlink(missing_ok=True)
            raise OSError("run file grant checksum mismatch")
        grant = RunFileGrant(record.id, run_id, record.filename, record.sha256, destination)
        grant_manifest = self._inside(run_root, record.id + ".grant.json")
        payload = {**grant.public(), "path": str(destination)}
        self._atomic_json(grant_manifest, payload)
        return grant

    def get_run_grant(
        self,
        *,
        owner_id: str,
        file_id: str,
        run_id: str,
    ) -> RunFileGrant:
        """Revalidate an owner-bound run grant before exposing its exact path."""
        self._validate_id("file_id", file_id)
        self._validate_id("run_id", run_id)
        record = self.get_user_file(file_id, owner_id=owner_id)
        run_root = self._inside(self.root, "runs", run_id, "uploads")
        manifest = self._inside(run_root, file_id + ".grant.json")
        if not manifest.is_file() or manifest.is_symlink():
            raise FileNotFoundError("run-authorized file grant was not found")
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            path = Path(str(payload["path"])).resolve()
            path.relative_to(run_root.resolve())
            grant = RunFileGrant(
                file_id=str(payload["file_id"]),
                run_id=str(payload["run_id"]),
                filename=str(payload["filename"]),
                sha256=str(payload["sha256"]),
                path=path,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FileWorkspaceViolation("run file grant manifest is invalid") from exc
        if grant.file_id != file_id or grant.run_id != run_id:
            raise FileWorkspaceViolation("run file grant identity mismatch")
        if grant.sha256 != record.sha256:
            raise FileWorkspaceViolation("run file grant owner checksum mismatch")
        if not grant.path.is_file() or grant.path.is_symlink():
            raise FileNotFoundError("run-authorized file content was not found")
        digest = hashlib.sha256(grant.path.read_bytes()).hexdigest()
        if digest != grant.sha256:
            raise OSError("run-authorized file checksum mismatch")
        return grant

    def list_run_grants(self, *, owner_id: str, run_id: str) -> tuple[RunFileGrant, ...]:
        self._validate_id("run_id", run_id)
        run_root = self._inside(self.root, "runs", run_id, "uploads")
        if not run_root.exists():
            return ()
        grants: list[RunFileGrant] = []
        for manifest in run_root.glob("*.grant.json"):
            file_id = manifest.name.removesuffix(".grant.json")
            grants.append(self.get_run_grant(owner_id=owner_id, file_id=file_id, run_id=run_id))
        return tuple(sorted(grants, key=lambda value: value.filename))

    def list_downloads(self, *, run_id: str) -> tuple[dict[str, Any], ...]:
        self._validate_id("run_id", run_id)
        run_root = self._inside(self.downloads_root, run_id)
        if not run_root.exists():
            return ()
        result: list[dict[str, Any]] = []
        for path in sorted(run_root.iterdir()):
            if not path.is_file() or path.is_symlink() or path.name.endswith(".part"):
                continue
            content = path.read_bytes()
            result.append(
                {
                    "filename": path.name,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "inert": True,
                }
            )
        return tuple(result)

    def _validate_file(self, filename: str, media_type: str, content: bytes) -> str:
        if not filename or len(filename) > 180 or "\x00" in filename:
            raise FileWorkspaceViolation("file name is empty, too long or invalid")
        if Path(filename).name != filename or filename in {".", ".."}:
            raise FileWorkspaceViolation("file name must not contain a path")
        extension = Path(filename).suffix.lower()
        normalized_type = media_type.lower().strip()
        if extension not in _ALLOWED_TYPES or normalized_type not in _ALLOWED_TYPES[extension]:
            raise FileWorkspaceViolation("file extension and media type are not allowlisted")
        if not content or len(content) > self.max_upload_bytes:
            raise FileWorkspaceViolation("file is empty or exceeds the upload size limit")
        if extension == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FileWorkspaceViolation("PNG content signature does not match its extension")
        if extension in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
            raise FileWorkspaceViolation("JPEG content signature does not match its extension")
        if extension == ".webp" and not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
            raise FileWorkspaceViolation("WebP content signature does not match its extension")
        if extension == ".pdf" and not content.startswith(b"%PDF-"):
            raise FileWorkspaceViolation("PDF content signature does not match its extension")
        if extension in {".docx", ".xlsx"} and not content.startswith(b"PK\x03\x04"):
            raise FileWorkspaceViolation("Office content signature does not match its extension")
        return filename

    def _write_manifest(self, record: UserFileRecord) -> None:
        manifest = self._inside(record.path.parent, record.id + ".json")
        payload = asdict(record)
        payload["path"] = str(record.path)
        self._atomic_json(manifest, payload)

    def _read_manifest(self, manifest: Path) -> UserFileRecord:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            path = Path(payload["path"]).resolve()
            path.relative_to(self.root)
            return UserFileRecord(**{**payload, "path": path})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FileWorkspaceViolation("user file manifest is invalid") from exc

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _owner_key(owner_id: str) -> str:
        if not owner_id:
            raise ValueError("owner_id is required")
        return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _validate_id(field: str, value: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise FileWorkspaceViolation(f"{field} must be a safe identifier")

    @staticmethod
    def _inside(root: Path, *parts: str) -> Path:
        root = root.resolve()
        candidate = root.joinpath(*parts).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise FileWorkspaceViolation("file path escapes its workspace") from exc
        return candidate
