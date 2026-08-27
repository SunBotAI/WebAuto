"""Shared isolation for legacy synchronous-async tests.

Several historical unittest helpers call ``get_event_loop().run_until_complete``
while other tests use ``asyncio.run`` (which closes and clears the current loop).
Python 3.12 no longer silently recreates that loop, so test order leaked process
state into otherwise passing modules.  Keep each test's loop ownership isolated.
"""

from __future__ import annotations

import asyncio

import pytest


def _fresh_default_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


@pytest.fixture(autouse=True)
def isolate_default_event_loop():
    loop = _fresh_default_loop()

    yield

    if not loop.is_closed() and not loop.is_running():
        loop.close()
    asyncio.set_event_loop(None)
