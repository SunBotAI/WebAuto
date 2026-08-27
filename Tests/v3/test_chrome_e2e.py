"""Authorized local-only Google Chrome E2E for the v3 runtime."""

import asyncio
import os
from pathlib import Path

import pytest

from webauto.domain import (
    Action,
    ActionKind,
    IdempotencyClass,
    RiskLevel,
    VerificationResult,
    VerificationStatus,
    VerifierSpec,
)
from webauto.runtime.artifacts import LocalArtifactStore
from webauto.runtime.browser import BrowserControl, ControlOwner
from webauto.runtime.browser.executor import ActionExecutor
from webauto.runtime.browser.lifecycle import PageLifecycle
from webauto.runtime.browser.observer import BrowserObserver
from webauto.runtime.browser.playwright_provider import DesktopManagedProvider


def test_real_google_chrome_local_action_upload_download_and_tabs(tmp_path: Path) -> None:
    executable = os.environ.get("WEBAUTO_CHROME_EXECUTABLE")
    if not executable or not os.path.exists(executable):
        pytest.skip("WEBAUTO_CHROME_EXECUTABLE is not available on this platform")
    asyncio.run(_run_chrome_e2e(tmp_path, executable))


async def _run_chrome_e2e(tmp_path: Path, executable: str) -> None:
    provider = DesktopManagedProvider(
        tmp_path / "profiles", headless=True, launch_options={"executable_path": executable}
    )
    try:
        session = await provider.start("e2e-profile")
        page = session.active_page
        await page.set_content(
            """
            <button id="submit" onclick="document.body.dataset.done='yes'">提交</button>
            <input id="upload" type="file">
            <a id="download" download="hello.txt" href="data:text/plain,hello">下载</a>
            """
        )
        observer = BrowserObserver(LocalArtifactStore(tmp_path / "artifacts"))
        control = BrowserControl()
        await control.acquire(ControlOwner.AGENT)

        async def verify(action, state):
            passed = (
                action.kind != ActionKind.CLICK
                or await page.get_attribute("body", "data-done") == "yes"
            )
            return VerificationResult(
                status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
                summary="真实 Chrome 页面已回读",
            )

        executor = ActionExecutor(observer=observer, verifier=verify, control=control)
        base = {
            "preconditions": ["local_fixture_ready"],
            "risk_level": RiskLevel.L1,
            "idempotency": IdempotencyClass.IDEMPOTENT,
            "verifier": VerifierSpec(kind="page_state", expectation={"fixture": True}),
        }
        clicked = await executor.execute(
            Action(kind=ActionKind.CLICK, target={"selector": "#submit"}, **base), session
        )
        assert clicked.succeeded

        upload_file = tmp_path / "upload.txt"
        upload_file.write_text("upload", encoding="utf-8")
        uploaded = await executor.execute(
            Action(
                kind=ActionKind.UPLOAD,
                target={"selector": "#upload"},
                arguments={"files": [str(upload_file)]},
                **base,
            ),
            session,
        )
        assert uploaded.succeeded

        downloaded = await executor.execute(
            Action(
                kind=ActionKind.DOWNLOAD,
                target={"selector": "#download"},
                arguments={"save_as": str(tmp_path / "hello.txt")},
                **base,
            ),
            session,
        )
        assert downloaded.succeeded
        assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"

        second = await session.context.new_page()
        await second.set_content("<p>second tab</p>")
        lifecycle = PageLifecycle(session)
        lifecycle.activate_page(second)
        assert len(lifecycle.pages) == 2
    finally:
        await provider.close()
