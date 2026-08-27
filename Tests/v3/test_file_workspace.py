"""User-file inbox, run grant and inert-download tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from webauto.runtime.file_workspace import FileWorkspaceViolation, RunFileWorkspace


def workspace(tmp_path: Path) -> RunFileWorkspace:
    return RunFileWorkspace(tmp_path / "files", tmp_path / "downloads", max_upload_bytes=1024)


def test_user_file_requires_allowlisted_type_signature_and_safe_name(tmp_path: Path) -> None:
    files = workspace(tmp_path)
    content = b"\x89PNG\r\n\x1a\n" + b"image"
    record = files.add_user_file(
        owner_id="local-user",
        filename="product.png",
        media_type="image/png",
        content=content,
    )

    assert record.public()["filename"] == "product.png"
    assert record.path.read_bytes() == content
    assert files.list_user_files(owner_id="local-user")[0].id == record.id

    with pytest.raises(FileWorkspaceViolation, match="path"):
        files.add_user_file(
            owner_id="local-user",
            filename="../escape.png",
            media_type="image/png",
            content=content,
        )
    with pytest.raises(FileWorkspaceViolation, match="allowlisted"):
        files.add_user_file(
            owner_id="local-user",
            filename="payload.exe",
            media_type="application/octet-stream",
            content=b"MZpayload",
        )
    with pytest.raises(FileWorkspaceViolation, match="signature"):
        files.add_user_file(
            owner_id="local-user",
            filename="spoofed.png",
            media_type="image/png",
            content=b"not-a-png",
        )


def test_run_grant_is_owner_bound_checksummed_and_isolated(tmp_path: Path) -> None:
    files = workspace(tmp_path)
    record = files.add_user_file(
        owner_id="owner-a",
        filename="facts.txt",
        media_type="text/plain",
        content=b"approved facts",
    )

    with pytest.raises(FileNotFoundError):
        files.authorize_for_run(owner_id="owner-b", file_id=record.id, run_id="run-1")
    with pytest.raises(FileWorkspaceViolation, match="run_id"):
        files.authorize_for_run(owner_id="owner-a", file_id=record.id, run_id="../run")

    grant = files.authorize_for_run(owner_id="owner-a", file_id=record.id, run_id="run-1")
    assert grant.path.read_bytes() == b"approved facts"
    assert grant.path != record.path
    assert grant.public()["sha256"] == record.sha256


def test_download_inventory_never_executes_or_follows_symlinks(tmp_path: Path) -> None:
    files = workspace(tmp_path)
    run_root = tmp_path / "downloads" / "run-1"
    run_root.mkdir(parents=True)
    (run_root / "report.pdf").write_bytes(b"%PDF-test")
    (run_root / "unfinished.part").write_bytes(b"partial")

    downloads = files.list_downloads(run_id="run-1")

    assert len(downloads) == 1
    assert downloads[0]["filename"] == "report.pdf"
    assert downloads[0]["inert"] is True
