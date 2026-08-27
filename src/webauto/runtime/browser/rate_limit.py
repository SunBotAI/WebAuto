"""Per-profile and per-site pacing for low-frequency personal automation."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class RateBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SiteRatePolicy:
    min_interval_seconds: float = 0.8
    max_actions_per_minute: int = 30
    cooldown_seconds: float = 60.0

    def __post_init__(self):
        if (
            self.min_interval_seconds < 0
            or self.max_actions_per_minute < 1
            or self.cooldown_seconds < 0
        ):
            raise ValueError("site rate policy values are invalid")


class SiteRateLimiter:
    def __init__(
        self,
        policy: SiteRatePolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.policy = policy or SiteRatePolicy()
        self._clock = clock
        self._sleep = sleeper
        self._history: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, profile_id: str, site: str) -> None:
        key = (profile_id, site.lower())
        async with self._locks[key]:
            now = self._clock()
            cooldown_until = self._cooldowns.get(key, 0)
            if now < cooldown_until:
                raise RateBudgetExceeded(f"site is cooling down for {cooldown_until - now:.1f}s")
            history = self._history[key]
            while history and now - history[0] >= 60:
                history.popleft()
            if len(history) >= self.policy.max_actions_per_minute:
                self._cooldowns[key] = now + self.policy.cooldown_seconds
                raise RateBudgetExceeded("site action budget exhausted; cooldown started")
            if history:
                delay = self.policy.min_interval_seconds - (now - history[-1])
                if delay > 0:
                    await self._sleep(delay)
                    now = self._clock()
            history.append(now)

    def trip_cooldown(self, profile_id: str, site: str) -> None:
        self._cooldowns[(profile_id, site.lower())] = self._clock() + self.policy.cooldown_seconds

    def remaining(self, profile_id: str, site: str) -> int:
        now = self._clock()
        history = self._history[(profile_id, site.lower())]
        while history and now - history[0] >= 60:
            history.popleft()
        return max(0, self.policy.max_actions_per_minute - len(history))
