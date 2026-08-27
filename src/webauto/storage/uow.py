"""Transaction boundary shared by persistence adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class AbstractUnitOfWork(ABC):
    """Commit a successful use case and roll back every failed use case."""

    async def __aenter__(self) -> Self:
        await self._open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None:
                await self.commit()
            else:
                await self.rollback()
        finally:
            await self._close()
        return False

    @abstractmethod
    async def _open(self) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    @abstractmethod
    async def _close(self) -> None: ...
