import pytest

from webauto.runtime.browser import RateBudgetExceeded, SiteRateLimiter, SiteRatePolicy


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


@pytest.mark.asyncio
async def test_site_rate_limiter_spaces_actions_and_scopes_by_profile():
    clock = Clock()

    async def sleep(seconds):
        clock.value += seconds

    limiter = SiteRateLimiter(
        SiteRatePolicy(min_interval_seconds=2, max_actions_per_minute=3), clock=clock, sleeper=sleep
    )
    await limiter.acquire("p1", "goofish.com")
    await limiter.acquire("p1", "goofish.com")
    assert clock.value == 2
    await limiter.acquire("p2", "goofish.com")
    assert clock.value == 2


@pytest.mark.asyncio
async def test_site_rate_limiter_trips_cooldown_when_budget_is_exhausted():
    clock = Clock()

    async def sleep(seconds):
        clock.value += seconds

    limiter = SiteRateLimiter(
        SiteRatePolicy(min_interval_seconds=0, max_actions_per_minute=2, cooldown_seconds=10),
        clock=clock,
        sleeper=sleep,
    )
    await limiter.acquire("p", "goofish.com")
    await limiter.acquire("p", "goofish.com")
    with pytest.raises(RateBudgetExceeded, match="budget exhausted"):
        await limiter.acquire("p", "goofish.com")
    clock.value += 5
    with pytest.raises(RateBudgetExceeded, match="cooling down"):
        await limiter.acquire("p", "goofish.com")
