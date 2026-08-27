"""B1-04 static no-bypass assertions.

Per v3.3 plan §17.3, the execution facade is the only place allowed to
import Playwright / Page / BrowserContext and the only place allowed to
reach into the legacy browser-agent stack (Butler / browser_agent /
local_execution / vertical_workflows / browser_session_*). Application- and
adapter-level modules that drive MCP or HTTP must go through
``webauto.application.mcp_browser.McpBrowserRuntime`` instead of
touching Playwright directly.

Legacy stack cleanup (application/{browser_agent,butler_service,
local_execution,vertical_workflows}.py and the legacy
webauto.agent_backends imports) is deferred to B4-01.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "webauto"

EXECUTION_FACADE_DIRS = {
    SRC_ROOT / "application" / "mcp_browser.py",  # sole entry point
    SRC_ROOT / "runtime" / "browser",  # shared browser runtime
}

LEGACY_MODULES = {
    "webauto.application.browser_agent",
    "webauto.application.butler_service",
    "webauto.application.local_execution",
    "webauto.application.vertical_workflows",
    "webauto.agent_backends.browser_use",
    "webauto.agent_backends.write_grants",
}

PLAYWRIGHT_MARKERS = {
    "playwright",
    "playwright.sync_api",
    "playwright.async_api",
    "BrowserContext",
    "Browser",
    "Page",
    "ElementHandle",
}

NON_FACADE_DIRS = [SRC_ROOT / "application", SRC_ROOT / "adapters"]


def _iter_non_facade_py() -> list[pathlib.Path]:
    """Files in application/ or adapters/ that are NOT part of the execution facade."""
    facade = {
        SRC_ROOT / "application" / "mcp_browser.py",
    }
    files: list[pathlib.Path] = []
    for directory in NON_FACADE_DIRS:
        for py_file in directory.rglob("*.py"):
            if py_file in facade:
                continue
            files.append(py_file)
    return files


def _imports_in(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _annotation_uses_playwright(node: ast.AST) -> bool:
    """Return True if the annotation AST references a Playwright marker as a name."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in PLAYWRIGHT_MARKERS:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in PLAYWRIGHT_MARKERS:
            return True
    return False


def _annotates_playwright(path: pathlib.Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.annotation:
            if _annotation_uses_playwright(node.annotation):
                return True
        if isinstance(node, ast.arg) and node.annotation:
            if _annotation_uses_playwright(node.annotation):
                return True
    return False


def test_execution_facade_files_clean() -> None:
    """The execution facade may import Playwright; everything else must not."""
    offenders: list[str] = []
    for py_file in _iter_non_facade_py():
        if py_file.name == "__init__.py":
            continue
        if _imports_in(py_file) & PLAYWRIGHT_MARKERS:
            offenders.append(f"{py_file.relative_to(REPO_ROOT)} imports Playwright")
        if _annotates_playwright(py_file):
            offenders.append(f"{py_file.relative_to(REPO_ROOT)} annotates Playwright types")
    assert not offenders, "Playwright is reserved for the execution facade:\n" + "\n".join(offenders)


def test_application_modules_do_not_import_legacy_stack() -> None:
    """application/ and adapters/ must not reach into the legacy browser-agent stack."""
    offenders: list[str] = []
    for py_file in _iter_non_facade_py():
        if py_file.name == "__init__.py":
            continue
        imports = _imports_in(py_file)
        for legacy in LEGACY_MODULES:
            if legacy in imports:
                offenders.append(f"{py_file.relative_to(REPO_ROOT)} imports {legacy}")
    assert not offenders, "Legacy stack must be reached through McpBrowserRuntime:\n" + "\n".join(offenders)


def test_application_modules_do_not_use_BrowserContext_or_Page() -> None:
    """No application/adapters module may type-hint Page or BrowserContext."""
    offenders: list[str] = []
    for py_file in _iter_non_facade_py():
        if py_file.name == "__init__.py":
            continue
        if _annotates_playwright(py_file):
            offenders.append(f"{py_file.relative_to(REPO_ROOT)} uses Page/BrowserContext")
    assert not offenders, "Page/BrowserContext annotations leak Playwright into adapters:\n" + "\n".join(offenders)


def test_facade_does_not_re_export_legacy_tools() -> None:
    import webauto.application.mcp_browser as mcp_browser  # noqa: F401 - side-effect import
    leaked = {
        name
        for name in dir(mcp_browser)
        if any(legacy.split(".")[-1] == name for legacy in LEGACY_MODULES)
    }
    assert not leaked, f"mcp_browser re-exports legacy symbols: {sorted(leaked)}"
