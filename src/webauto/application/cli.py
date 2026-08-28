"""Command-line transport for the unified WebAuto application service."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from .adapters import CliAdapter
from .butler_service import ButlerService
from .entrypoints import actor_from_payload
from .utils import jsonable
from .service import ApplicationService
from .settings import RuntimeConfigStore


def _default_service() -> ApplicationService:
    from webauto.bootstrap import get_application_service

    return get_application_service()


async def execute(
    operation: str,
    payload: dict[str, Any],
    *,
    service: ApplicationService | None = None,
    butler: ButlerService | None = None,
    settings_store: RuntimeConfigStore | None = None,
) -> dict[str, Any]:
    arguments = dict(payload)
    if operation in {"butler_message", "task_continue"} or operation.startswith(
        ("settings_", "browser_session_")
    ):
        from .mcp import call_tool

        return await call_tool(
            operation, arguments, service=service, butler=butler, settings_store=settings_store
        )
    try:
        actor = actor_from_payload(arguments)
        result = await CliAdapter(service or _default_service()).invoke(
            operation, actor=actor, **arguments
        )
        return {"success": True, "data": jsonable(result), "error": None}
    except Exception as exc:  # noqa: BLE001 - CLI boundary maps failures
        return {"success": False, "data": None, "error": str(exc)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WebAuto v3 unified CLI")
    parser.add_argument(
        "operation", help="Operation, for example butler_message, settings_get or create_goal"
    )
    parser.add_argument(
        "--payload", required=True, help="JSON object with operation arguments and auth context"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.payload)
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
    except (json.JSONDecodeError, TypeError) as exc:
        print(json.dumps({"success": False, "data": None, "error": str(exc)}, ensure_ascii=False))
        return 2
    result = asyncio.run(execute(args.operation, payload))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
