"""Translate WebAuto browser identity configuration into an agent session plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from webauto.application.settings import RuntimeConfigStore
from webauto.domain import Placement

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class BrowserAgentSessionPlan:
    id: str
    run_id: str
    profile_id: str
    placement: Placement
    allowed_domains: tuple[str, ...]
    downloads_path: Path
    cdp_url: str | None = None
    executable_path: str | None = None
    user_data_dir: Path | None = None
    headless: bool = False

    def browser_use_options(self) -> dict[str, Any]:
        browser_domains = [
            (urlparse(scope).hostname or scope) if "://" in scope else scope
            for scope in self.allowed_domains
        ]
        options: dict[str, Any] = {
            "allowed_domains": browser_domains,
            "downloads_path": str(self.downloads_path),
            "keep_alive": True,
            "accept_downloads": False,
            "auto_download_pdfs": False,
        }
        if self.cdp_url:
            options["cdp_url"] = self.cdp_url
            return options
        if self.executable_path:
            options["executable_path"] = self.executable_path
        if self.user_data_dir:
            options["user_data_dir"] = str(self.user_data_dir)
        options["headless"] = self.headless
        return options


class BrowserAgentSessionBridge:
    """Prepare one identity-bound plan; the selected backend is the sole browser owner."""

    def __init__(self, store: RuntimeConfigStore) -> None:
        self._store = store

    def prepare(
        self,
        *,
        run_id: str,
        profile_id: str,
        allowed_domains: tuple[str, ...],
    ) -> BrowserAgentSessionPlan:
        self._validate_id("run_id", run_id)
        self._validate_id("profile_id", profile_id)
        if not allowed_domains or not all(item.strip() for item in allowed_domains):
            raise ValueError("allowed_domains must contain at least one non-blank domain")

        values = self._store.load()
        browser = values["browser"]
        mode = browser["mode"]
        downloads = (self._store.runtime_dir / "downloads" / run_id).resolve()
        downloads.mkdir(parents=True, exist_ok=True)

        common = {
            "id": str(uuid4()),
            "run_id": run_id,
            "profile_id": profile_id,
            "allowed_domains": tuple(item.strip() for item in allowed_domains),
            "downloads_path": downloads,
        }
        if mode == "cdp":
            endpoint = str(browser.get("cdp_endpoint") or "").strip()
            if not endpoint:
                raise ValueError("browser.cdp_endpoint is required in CDP mode")
            return BrowserAgentSessionPlan(
                **common,
                placement=Placement.BROWSER_ATTACH,
                cdp_url=endpoint,
            )
        if mode == "managed":
            profiles_root = Path(values["storage"]["profiles_dir"]).resolve()
            user_data_dir = (profiles_root / profile_id).resolve()
            try:
                user_data_dir.relative_to(profiles_root)
            except ValueError as exc:
                raise ValueError("profile_id escapes the configured profiles directory") from exc
            user_data_dir.mkdir(parents=True, exist_ok=True)
            executable = str(browser.get("executable") or "").strip() or None
            return BrowserAgentSessionPlan(
                **common,
                placement=Placement.DESKTOP_MANAGED,
                executable_path=executable,
                user_data_dir=user_data_dir,
                headless=bool(browser.get("headless")),
            )
        raise RuntimeError("remote browser agent sessions are not enabled in the local release")

    @staticmethod
    def _validate_id(field: str, value: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(f"{field} must be a safe identifier")
