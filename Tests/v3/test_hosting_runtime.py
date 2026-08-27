"""Remote dedicated hosting, tenant isolation, ACK recovery and backup tests."""

from pathlib import Path

import pytest

from webauto.runtime.hosting import (
    BackupManager,
    CommandLedger,
    RemoteDedicatedManager,
    TenantIsolationRegistry,
)


@pytest.mark.asyncio
async def test_remote_dedicated_uses_tenant_scoped_volume_and_single_writer(tmp_path: Path) -> None:
    manager = RemoteDedicatedManager(tmp_path)
    first = await manager.allocate("tenant-1", "profile-1", "node-1")
    assert first.volume.is_relative_to(tmp_path)
    assert "tenant-1" not in str(first.volume)
    with pytest.raises(RuntimeError, match="tenant"):
        await manager.allocate("tenant-2", "profile-1", "node-2")
    with pytest.raises(RuntimeError, match="writer"):
        await manager.allocate("tenant-1", "profile-1", "node-2")
    await manager.release(first)
    second = await manager.allocate("tenant-1", "profile-1", "node-2")
    assert second.fencing_token > first.fencing_token


def test_tenant_isolation_registry_scopes_all_sensitive_resources() -> None:
    isolation = TenantIsolationRegistry()
    for kind in ("profiles", "cookies", "artifacts", "memory", "runs", "logs"):
        isolation.bind("tenant-1", kind, "resource-1")
        assert isolation.authorize("tenant-1", kind, "resource-1")
        assert not isolation.authorize("tenant-2", kind, "resource-1")


def test_command_ledger_resends_only_unacknowledged_commands() -> None:
    ledger = CommandLedger()
    one = ledger.issue("device-1", {"kind": "health"})
    two = ledger.issue("device-1", {"kind": "browser.start"})
    ledger.ack("device-1", one.id)
    assert [command.id for command in ledger.pending("device-1")] == [two.id]
    with pytest.raises(PermissionError):
        ledger.ack("device-2", two.id)


def test_backup_manifest_detects_corruption_and_restores(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "profiles.json").write_text('{"profile":"p1"}', encoding="utf-8")
    (source / "config.json").write_text('{"version":1}', encoding="utf-8")
    backup_root = tmp_path / "backups"
    manager = BackupManager(backup_root)
    manifest = manager.create(source)
    assert manager.verify(manifest)
    restored = tmp_path / "restored"
    manager.restore(manifest, restored)
    assert (restored / "profiles.json").read_text(encoding="utf-8") == '{"profile":"p1"}'
    manifest.files["profiles.json"].write_text("corrupt", encoding="utf-8")
    assert not manager.verify(manifest)
