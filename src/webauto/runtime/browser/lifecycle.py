"""Explicit Browser/Context/Page lifecycle semantics."""

from __future__ import annotations

from .contracts import BrowserSession


def _is_closed(page) -> bool:
    value = getattr(page, "is_closed", None)
    if callable(value):
        return bool(value())
    return bool(getattr(page, "closed", False))


class PageLifecycle:
    def __init__(self, session: BrowserSession) -> None:
        if session.context is None:
            raise RuntimeError("browser session has no context")
        self._session = session

    @property
    def pages(self) -> tuple[object, ...]:
        return tuple(page for page in self._session.context.pages if not _is_closed(page))

    @property
    def frames(self) -> tuple[object, ...]:
        page = self._session.active_page
        return tuple(page.frames) if page is not None else ()

    def activate(self, index: int) -> object:
        page = self.pages[index]
        self._session.active_page = page
        return page

    async def close_active(self) -> None:
        page = self._session.active_page
        if page is None:
            return
        await page.close()
        remaining = self.pages
        self._session.active_page = remaining[-1] if remaining else None

    def activate_page(self, page: object) -> None:
        if page not in self.pages:
            raise ValueError("page does not belong to this session")
        self._session.active_page = page
