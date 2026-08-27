"""Secret-free MCP client configuration rendered by the Web setup surface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .mcp import list_agent_tools
from .settings import RuntimeConfigStore


def build_mcp_client_config(
    store: RuntimeConfigStore,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Return copy-ready stdio configuration without returning either token value."""
    root = (project_root or Path.cwd()).resolve()
    command, args = _stdio_command(root)
    server = {"command": command, "args": args}
    generic = {"mcpServers": {"webauto": server}}
    tools = list_agent_tools()
    args_toml = ", ".join(json.dumps(value, ensure_ascii=False) for value in args)
    codex_toml = "\n".join(
        (
            "[mcp_servers.webauto]",
            f"command = {json.dumps(command, ensure_ascii=False)}",
            f"args = [{args_toml}]",
            "startup_timeout_sec = 30",
            "tool_timeout_sec = 120",
        )
    )
    return {
        "mode": "mcp-first",
        "web_role": "configuration_only",
        "agent_role": "The external MCP client owns planning, reasoning and task orchestration.",
        "transport": "stdio",
        "server": server,
        "generic_json": json.dumps(generic, ensure_ascii=False, indent=2),
        "codex_toml": codex_toml,
        "tool_count": len(tools),
        "tool_names": [item["name"] for item in tools],
        "authentication": {
            "mode": "trusted_local_stdio",
            "credential_injected_by_server": True,
            "credential_visible_to_agent": False,
            "token_path": str(store.mcp_authorizer.token_path),
            "note": (
                "The local stdio server reads its own credential. Do not put mcp_token in "
                "prompts or client configuration. HTTP transport does not auto-inject it."
            ),
        },
        "requirements": {
            "web_server_required": False,
            "internal_model_required": False,
            "manual_browser_path_required": False,
            "postgres_required_for_local_personal_mode": False,
            "redis_required_for_local_stdio": False,
            "website_credentials_stored_by_webauto": False,
        },
    }


def _stdio_command(root: Path) -> tuple[str, list[str]]:
    posix = root.as_posix()
    if os.name != "nt" and posix.startswith("/mnt/"):
        return (
            "wsl.exe",
            [
                "--cd",
                posix,
                "-e",
                ".venv/bin/python",
                "-m",
                "webauto.adapters.mcp_server",
                "--transport",
                "stdio",
            ],
        )
    if os.name == "nt":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    executable = str(candidate if candidate.is_file() else Path(sys.executable))
    return (
        executable,
        ["-m", "webauto.adapters.mcp_server", "--transport", "stdio"],
    )


__all__ = ["build_mcp_client_config"]
