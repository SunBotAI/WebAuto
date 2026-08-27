"""Pause, human takeover and control-return state machine."""

from __future__ import annotations

from enum import Enum

from .contracts import BrowserControl, ControlOwner


class LiveState(str, Enum):
    IDLE = "idle"
    AGENT = "agent"
    PAUSED = "paused"
    HUMAN = "human"


class LiveBrowserController:
    def __init__(self, control: BrowserControl) -> None:
        self._control = control
        self._state = LiveState.IDLE

    @property
    def state(self) -> LiveState:
        return self._state

    async def start_agent_control(self) -> None:
        await self._control.acquire(ControlOwner.AGENT)
        self._state = LiveState.AGENT

    async def pause(self) -> None:
        if self._control.owner == ControlOwner.AGENT:
            await self._control.release(ControlOwner.AGENT)
        self._state = LiveState.PAUSED

    async def takeover(self) -> None:
        if self._control.owner == ControlOwner.AGENT:
            await self._control.release(ControlOwner.AGENT)
        await self._control.acquire(ControlOwner.HUMAN)
        self._state = LiveState.HUMAN

    async def return_to_agent(self) -> None:
        if self._control.owner != ControlOwner.HUMAN:
            raise RuntimeError("human does not own browser control")
        await self._control.release(ControlOwner.HUMAN)
        await self._control.acquire(ControlOwner.AGENT)
        self._state = LiveState.AGENT
