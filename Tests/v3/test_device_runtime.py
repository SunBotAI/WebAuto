"""M7 device pairing, signed channel, placement and secret-vault tests."""

from datetime import datetime, timedelta, timezone

import pytest

from webauto.domain import Placement, RiskLevel
from webauto.runtime.device import (
    CapacityManager,
    DevicePairingService,
    DeviceRevoked,
    LocalDeviceAgent,
    NodeDescriptor,
    PlacementPolicy,
    ReplayDetected,
    SecretVault,
    sign_command,
)


def test_one_time_pairing_device_revocation_and_rotation() -> None:
    cryptography = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    private = cryptography.Ed25519PrivateKey.generate()
    service = DevicePairingService()
    code = service.create_pairing_code("tenant-1", "user-1")
    device = service.pair(code.value, "laptop", private.public_key())
    with pytest.raises(ValueError, match="used"):
        service.pair(code.value, "second", private.public_key())
    replacement = cryptography.Ed25519PrivateKey.generate()
    rotated = service.rotate(device.id, replacement.public_key())
    assert rotated.key_version == 2
    service.revoke(device.id)
    assert service.get(device.id).revoked_at is not None


def test_signed_command_rejects_replay_expiry_revocation_and_secret_payload() -> None:
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    private = crypto.Ed25519PrivateKey.generate()
    pairing = DevicePairingService()
    code = pairing.create_pairing_code("tenant-1", "user-1")
    device = pairing.pair(code.value, "laptop", private.public_key())
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    agent = LocalDeviceAgent(device.id, pairing, clock=lambda: now)
    command = sign_command(
        private,
        device_id=device.id,
        tenant_id="tenant-1",
        kind="browser.health",
        payload={"profile_ref": "profile-1"},
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        nonce="nonce-1",
        key_version=device.key_version,
    )
    assert agent.accept(command)["accepted"]
    with pytest.raises(ReplayDetected):
        agent.accept(command)

    secret_command = sign_command(
        private,
        device_id=device.id,
        tenant_id="tenant-1",
        kind="browser.start",
        payload={"cookie": "session=secret"},
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        nonce="nonce-2",
        key_version=device.key_version,
    )
    with pytest.raises(ValueError, match="secret"):
        agent.accept(secret_command)

    pairing.revoke(device.id)
    fresh = sign_command(
        private,
        device_id=device.id,
        tenant_id="tenant-1",
        kind="browser.health",
        payload={},
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        nonce="nonce-3",
        key_version=device.key_version,
    )
    with pytest.raises(DeviceRevoked):
        agent.accept(fresh)


def test_placement_policy_does_not_silently_move_bound_profile() -> None:
    nodes = [
        NodeDescriptor("local-1", Placement.LOCAL_DEVICE_AGENT, True, {"upload"}, "tenant-1", 1),
        NodeDescriptor("remote-1", Placement.REMOTE_DEDICATED, True, {"upload"}, "tenant-1", 5),
    ]
    policy = PlacementPolicy()
    selected = policy.select(
        tenant_id="tenant-1",
        nodes=nodes,
        required_features={"upload"},
        risk_level=RiskLevel.L2,
        bound_placement=Placement.LOCAL_DEVICE_AGENT,
    )
    assert selected.id == "local-1"
    nodes[0] = NodeDescriptor(
        "local-1", Placement.LOCAL_DEVICE_AGENT, False, {"upload"}, "tenant-1", 1
    )
    with pytest.raises(RuntimeError, match="WAITING_NODE"):
        policy.select(
            tenant_id="tenant-1",
            nodes=nodes,
            required_features={"upload"},
            risk_level=RiskLevel.L2,
            bound_placement=Placement.LOCAL_DEVICE_AGENT,
        )


def test_secret_vault_uses_short_lived_device_scoped_references() -> None:
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    vault = SecretVault(clock=lambda: now)
    vault.store("tenant-1", "store-login", "top-secret")
    grant = vault.grant(
        tenant_id="tenant-1",
        secret_name="store-login",
        device_id="device-1",
        ttl=timedelta(seconds=30),
    )
    assert "top-secret" not in repr(grant)
    assert (
        vault.resolve(grant.reference, tenant_id="tenant-1", device_id="device-1") == "top-secret"
    )
    with pytest.raises(PermissionError):
        vault.resolve(grant.reference, tenant_id="tenant-1", device_id="device-2")
    assert [entry.action for entry in vault.audit_log] == [
        "secret.store",
        "secret.grant",
        "secret.resolve",
    ]


def test_capacity_manager_enforces_tenant_browser_and_model_budgets() -> None:
    capacity = CapacityManager(browser_slots={"tenant-1": 1}, model_budget={"tenant-1": 2.0})
    capacity.acquire_browser("tenant-1")
    with pytest.raises(RuntimeError, match="browser quota"):
        capacity.acquire_browser("tenant-1")
    capacity.release_browser("tenant-1")
    capacity.consume_model_budget("tenant-1", 1.5)
    with pytest.raises(RuntimeError, match="model budget"):
        capacity.consume_model_budget("tenant-1", 0.6)
