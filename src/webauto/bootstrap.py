"""Composition root for WebAuto product entry points."""

from __future__ import annotations

import os
from threading import Lock

from webauto.application.butler_service import ButlerService
from webauto.application.service import ApplicationService
from webauto.application.settings import RuntimeConfigStore
from webauto.application.state import JsonApplicationStateStore
from webauto.config import RuntimeSettings, SecretValue
from webauto.storage.application_state import PostgresApplicationStateStore

_service: ApplicationService | None = None
_service_lock = Lock()
_butler_service: ButlerService | None = None
_butler_lock = Lock()


def get_application_service() -> ApplicationService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                settings = RuntimeSettings.from_env()
                configured = RuntimeConfigStore(settings.runtime_dir)
                saved = configured.load()
                database_url = settings.database_url or SecretValue(
                    configured.secret("database_url")
                )
                environment = os.environ.get(
                    "WEBAUTO_ENV", str(saved.get("environment", "development"))
                ).lower()
                if database_url:
                    store = PostgresApplicationStateStore(database_url)
                elif environment == "production":
                    raise RuntimeError("WEBAUTO_DATABASE_URL is required in production")
                else:
                    store = JsonApplicationStateStore(
                        settings.runtime_dir / "application-state.json"
                    )
                _service = ApplicationService(state_store=store)
    return _service


def get_butler_service(
    settings_store: RuntimeConfigStore | None = None,
) -> ButlerService:
    """Return one Butler so browser/profile sessions survive transport calls."""

    global _butler_service
    if _butler_service is None:
        with _butler_lock:
            if _butler_service is None:
                from webauto.application.browser_agent import build_butler_service

                store = settings_store or RuntimeConfigStore(RuntimeSettings.from_env().runtime_dir)
                _butler_service = build_butler_service(get_application_service(), store)
    return _butler_service
