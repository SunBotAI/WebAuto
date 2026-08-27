"""Browser runtime contract tests independent of a real browser binary."""

import asyncio

import pytest

from webauto.domain import Placement
from webauto.runtime.browser import (
    BrowserCapabilities,
    BrowserControl,
    BrowserHealth,
    BrowserProvider,
    BrowserSession,
    ControlOwner,
    InMemoryLeaseManager,
    LeaseConflict,
)


class FakeProvider(BrowserProvider):
    def __init__(self, placement: Placement) -> None:
        self._placement = placement
        self.closed = False

    @property
    def capabilities(self) -> BrowserCapabilities:
        return BrowserCapabilities(
            placement=self._placement,
            persistent_profile=self._placement == Placement.DESKTOP_MANAGED,
            can_launch=self._placement == Placement.DESKTOP_MANAGED,
            can_attach=True,
            supports_tracing=True,
            supports_downloads=True,
            supports_uploads=True,
            supports_multi_page=True,
        )

    async def start(self, profile_id: str) -> BrowserSession:
        return BrowserSession(id="session-1", profile_id=profile_id, placement=self._placement)

    async def connect(self, endpoint: str, profile_id: str) -> BrowserSession:
        return BrowserSession(id="session-2", profile_id=profile_id, placement=self._placement)

    async def health(self) -> BrowserHealth:
        return BrowserHealth(healthy=not self.closed, message="ok")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("placement", [Placement.DESKTOP_MANAGED, Placement.BROWSER_ATTACH])
async def test_providers_share_one_contract(placement: Placement) -> None:
    provider = FakeProvider(placement)
    session = await provider.start("profile-1")

    assert session.profile_id == "profile-1"
    assert provider.capabilities.supports_uploads
    assert (await provider.health()).healthy

    await provider.close()
    assert not (await provider.health()).healthy


@pytest.mark.asyncio
async def test_profile_lease_has_single_writer_and_monotonic_fencing_token() -> None:
    leases = InMemoryLeaseManager()
    first = await leases.acquire("profile-1", "worker-a", Placement.DESKTOP_MANAGED)

    with pytest.raises(LeaseConflict):
        await leases.acquire("profile-1", "worker-b", Placement.DESKTOP_MANAGED)

    await leases.release(first)
    second = await leases.acquire("profile-1", "worker-b", Placement.DESKTOP_MANAGED)
    assert second.fencing_token > first.fencing_token


@pytest.mark.asyncio
async def test_profile_lease_cannot_silently_change_placement() -> None:
    leases = InMemoryLeaseManager()
    lease = await leases.acquire("profile-1", "worker-a", Placement.DESKTOP_MANAGED)
    await leases.release(lease)

    with pytest.raises(LeaseConflict, match="placement"):
        await leases.acquire("profile-1", "worker-b", Placement.BROWSER_ATTACH)


@pytest.mark.asyncio
async def test_human_takeover_excludes_agent_control() -> None:
    control = BrowserControl()
    await control.acquire(ControlOwner.AGENT)
    await control.release(ControlOwner.AGENT)
    await control.acquire(ControlOwner.HUMAN)

    with pytest.raises(RuntimeError, match="human"):
        await control.acquire(ControlOwner.AGENT)

    await control.release(ControlOwner.HUMAN)
    await asyncio.wait_for(control.acquire(ControlOwner.AGENT), timeout=0.1)
