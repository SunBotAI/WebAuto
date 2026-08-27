"""Local-device and remote-node trust, placement and secret-reference runtime."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from webauto.domain import Placement, RiskLevel


@dataclass(frozen=True, slots=True)
class PairingCode:
    id: str
    tenant_id: str
    user_id: str
    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    id: str
    tenant_id: str
    name: str
    public_key: bytes = field(repr=False)
    key_version: int = 1
    revoked_at: datetime | None = None


class DeviceRevoked(PermissionError):
    pass


class ReplayDetected(PermissionError):
    pass


class DevicePairingService:
    def __init__(self) -> None:
        self._codes: dict[str, dict[str, Any]] = {}
        self._devices: dict[str, DeviceRecord] = {}

    def create_pairing_code(self, tenant_id: str, user_id: str) -> PairingCode:
        value = secrets.token_urlsafe(24)
        code = PairingCode(str(uuid4()), tenant_id, user_id, value)
        self._codes[code.id] = {
            "digest": hashlib.sha256(value.encode()).digest(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "used": False,
        }
        return code

    def pair(self, value: str, name: str, public_key: Ed25519PublicKey) -> DeviceRecord:
        digest = hashlib.sha256(value.encode()).digest()
        match = next(
            (
                item
                for item in self._codes.values()
                if secrets.compare_digest(item["digest"], digest)
            ),
            None,
        )
        if match is None:
            raise ValueError("invalid pairing code")
        if match["used"]:
            raise ValueError("pairing code has already been used")
        match["used"] = True
        encoded = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        device = DeviceRecord(str(uuid4()), match["tenant_id"], name, encoded)
        self._devices[device.id] = device
        return device

    def get(self, device_id: str) -> DeviceRecord:
        return self._devices[device_id]

    def rotate(self, device_id: str, public_key: Ed25519PublicKey) -> DeviceRecord:
        current = self._devices[device_id]
        if current.revoked_at is not None:
            raise DeviceRevoked(device_id)
        encoded = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        updated = DeviceRecord(
            current.id, current.tenant_id, current.name, encoded, current.key_version + 1
        )
        self._devices[device_id] = updated
        return updated

    def revoke(self, device_id: str) -> None:
        current = self._devices[device_id]
        self._devices[device_id] = DeviceRecord(
            current.id,
            current.tenant_id,
            current.name,
            current.public_key,
            current.key_version,
            datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class SignedCommand:
    device_id: str
    tenant_id: str
    kind: str
    payload: dict[str, Any]
    issued_at: datetime
    expires_at: datetime
    nonce: str
    key_version: int
    signature: bytes = field(repr=False)

    def signing_bytes(self) -> bytes:
        body = {
            "device_id": self.device_id,
            "tenant_id": self.tenant_id,
            "kind": self.kind,
            "payload": self.payload,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "nonce": self.nonce,
            "key_version": self.key_version,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_command(
    private_key: Ed25519PrivateKey,
    *,
    device_id: str,
    tenant_id: str,
    kind: str,
    payload: dict[str, Any],
    issued_at: datetime,
    expires_at: datetime,
    nonce: str,
    key_version: int,
) -> SignedCommand:
    unsigned = SignedCommand(
        device_id, tenant_id, kind, payload, issued_at, expires_at, nonce, key_version, b""
    )
    return SignedCommand(
        device_id,
        tenant_id,
        kind,
        payload,
        issued_at,
        expires_at,
        nonce,
        key_version,
        private_key.sign(unsigned.signing_bytes()),
    )


def _reject_secrets(payload: Any, path: str = "$") -> None:
    forbidden = {
        "cookie",
        "cookies",
        "token",
        "password",
        "secret",
        "database_url",
        "authorization",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in forbidden:
                raise ValueError(f"secret field is forbidden in device command at {path}.{key}")
            _reject_secrets(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _reject_secrets(value, f"{path}[{index}]")


class LocalDeviceAgent:
    def __init__(
        self,
        device_id: str,
        pairing: DevicePairingService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.device_id = device_id
        self._pairing = pairing
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonces: set[str] = set()

    def accept(self, command: SignedCommand) -> dict[str, Any]:
        device = self._pairing.get(self.device_id)
        if device.revoked_at is not None:
            raise DeviceRevoked(self.device_id)
        if command.device_id != device.id or command.tenant_id != device.tenant_id:
            raise PermissionError("command scope mismatch")
        if command.key_version != device.key_version:
            raise PermissionError("command key version is stale")
        now = self._clock()
        if command.issued_at > now + timedelta(seconds=30) or command.expires_at <= now:
            raise PermissionError("command is outside its validity window")
        Ed25519PublicKey.from_public_bytes(device.public_key).verify(
            command.signature, command.signing_bytes()
        )
        if command.nonce in self._nonces:
            raise ReplayDetected(command.nonce)
        _reject_secrets(command.payload)
        self._nonces.add(command.nonce)
        return {"accepted": True, "kind": command.kind, "nonce": command.nonce}


@dataclass(frozen=True, slots=True)
class NodeDescriptor:
    id: str
    placement: Placement
    online: bool
    features: set[str]
    tenant_id: str
    available_slots: int


class PlacementPolicy:
    def select(
        self,
        *,
        tenant_id: str,
        nodes: list[NodeDescriptor],
        required_features: set[str],
        risk_level: RiskLevel,
        bound_placement: Placement | None = None,
    ) -> NodeDescriptor:
        scoped = [node for node in nodes if node.tenant_id == tenant_id]
        if bound_placement is not None:
            scoped = [node for node in scoped if node.placement == bound_placement]
        eligible = [
            node
            for node in scoped
            if node.online and node.available_slots > 0 and required_features <= node.features
        ]
        if not eligible:
            if bound_placement is not None:
                raise RuntimeError("WAITING_NODE: bound placement is unavailable")
            raise RuntimeError("no eligible browser node")
        if risk_level.rank >= RiskLevel.L3.rank:
            dedicated = [node for node in eligible if node.placement != Placement.BROWSER_ATTACH]
            if dedicated:
                eligible = dedicated
        return max(eligible, key=lambda node: node.available_slots)


@dataclass(frozen=True, slots=True)
class SecretGrant:
    reference: str
    tenant_id: str
    secret_name: str
    device_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VaultAudit:
    action: str
    tenant_id: str
    secret_name: str
    device_id: str | None = None


class SecretVault:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._secrets: dict[tuple[str, str], str] = {}
        self._grants: dict[str, SecretGrant] = {}
        self._audit: list[VaultAudit] = []

    @property
    def audit_log(self) -> tuple[VaultAudit, ...]:
        return tuple(self._audit)

    def store(self, tenant_id: str, name: str, value: str) -> None:
        self._secrets[(tenant_id, name)] = value
        self._audit.append(VaultAudit("secret.store", tenant_id, name))

    def grant(
        self, *, tenant_id: str, secret_name: str, device_id: str, ttl: timedelta
    ) -> SecretGrant:
        if (tenant_id, secret_name) not in self._secrets:
            raise KeyError(secret_name)
        if ttl.total_seconds() <= 0:
            raise ValueError("grant ttl must be positive")
        reference = "secret-ref:" + secrets.token_urlsafe(24)
        grant = SecretGrant(reference, tenant_id, secret_name, device_id, self._clock() + ttl)
        self._grants[reference] = grant
        self._audit.append(VaultAudit("secret.grant", tenant_id, secret_name, device_id))
        return grant

    def resolve(self, reference: str, *, tenant_id: str, device_id: str) -> str:
        grant = self._grants[reference]
        if grant.tenant_id != tenant_id or grant.device_id != device_id:
            raise PermissionError("secret grant scope mismatch")
        if self._clock() >= grant.expires_at:
            raise PermissionError("secret grant expired")
        self._audit.append(VaultAudit("secret.resolve", tenant_id, grant.secret_name, device_id))
        return self._secrets[(tenant_id, grant.secret_name)]


class CapacityManager:
    def __init__(self, *, browser_slots: dict[str, int], model_budget: dict[str, float]) -> None:
        self._slots = dict(browser_slots)
        self._in_use: dict[str, int] = {}
        self._budget = dict(model_budget)
        self._spent: dict[str, float] = {}

    def acquire_browser(self, tenant_id: str) -> None:
        used = self._in_use.get(tenant_id, 0)
        if used >= self._slots.get(tenant_id, 0):
            raise RuntimeError("browser quota exceeded")
        self._in_use[tenant_id] = used + 1

    def release_browser(self, tenant_id: str) -> None:
        self._in_use[tenant_id] = max(0, self._in_use.get(tenant_id, 0) - 1)

    def consume_model_budget(self, tenant_id: str, cost: float) -> None:
        spent = self._spent.get(tenant_id, 0.0)
        if spent + cost > self._budget.get(tenant_id, 0.0):
            raise RuntimeError("model budget exceeded")
        self._spent[tenant_id] = spent + cost
