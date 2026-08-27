"""Structured browser Action executor shared by all providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import urlparse

from webauto.domain import (
    Action,
    ActionKind,
    ActionResult,
    ActionStatus,
    ErrorCategory,
    PageState,
    VerificationResult,
    VerificationStatus,
)

from .contracts import BrowserControl, BrowserSession, ControlOwner
from .observer import BrowserObserver
from .rate_limit import RateBudgetExceeded, SiteRateLimiter
from .reliability import ChallengeDetector

Verifier = Callable[[Action, PageState], Awaitable[VerificationResult]]
ApprovalChecker = Callable[[Action, BrowserSession], Awaitable[bool]]


class ActionExecutor:
    def __init__(
        self,
        *,
        observer: BrowserObserver,
        verifier: Verifier,
        control: BrowserControl,
        approval_checker: ApprovalChecker | None = None,
        challenge_detector: ChallengeDetector | None = None,
        rate_limiter: SiteRateLimiter | None = None,
    ) -> None:
        self._observer = observer
        self._verifier = verifier
        self._control = control
        self._approval_checker = approval_checker
        self._challenge_detector = challenge_detector or ChallengeDetector()
        self._rate_limiter = rate_limiter

    async def execute(self, action: Action, session: BrowserSession) -> ActionResult:
        if self._control.owner == ControlOwner.HUMAN:
            raise RuntimeError("browser is controlled by human")
        if self._control.owner != ControlOwner.AGENT:
            raise RuntimeError("agent does not own browser control")
        if action.requires_approval:
            if not action.approval_id or self._approval_checker is None:
                raise PermissionError("approved action binding is required")
            if not await self._approval_checker(action, session):
                raise PermissionError("approval is invalid for this action or session")

        started = datetime.now(timezone.utc)
        page = session.active_page
        target_url = str(action.arguments.get("url") or getattr(page, "url", ""))
        site = urlparse(target_url).hostname or "local"
        if self._rate_limiter is not None:
            try:
                await self._rate_limiter.acquire(session.profile_id, site)
            except RateBudgetExceeded as exc:
                return ActionResult(
                    action_id=action.id,
                    status=ActionStatus.BLOCKED,
                    verification=VerificationResult(
                        status=VerificationStatus.NOT_RUN, summary="site rate budget blocked action"
                    ),
                    started_at=started,
                    finished_at=datetime.now(timezone.utc),
                    error_category=ErrorCategory.POLICY_BLOCKED,
                    error_message=str(exc),
                )
        output = await self._dispatch(action, session)
        state = await self._observer.observe(session)
        challenge = self._challenge_detector.detect(state)
        if challenge.detected:
            if self._rate_limiter is not None:
                self._rate_limiter.trip_cooldown(session.profile_id, site)
            evidence = [state.screenshot_artifact_id] if state.screenshot_artifact_id else []
            return ActionResult(
                action_id=action.id,
                status=ActionStatus.BLOCKED,
                verification=VerificationResult(
                    status=VerificationStatus.NOT_RUN,
                    summary=f"browser challenge detected: {challenge.kind.value}",
                    evidence_ids=evidence,
                    observed={
                        "challenge": challenge.kind.value,
                        "confidence": challenge.confidence,
                    },
                ),
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                output={
                    "challenge": challenge.kind.value,
                    "confidence": challenge.confidence,
                    "evidence": list(challenge.evidence),
                    "requires_human": challenge.requires_human,
                },
                evidence_ids=evidence,
                error_category=ErrorCategory.AUTH_REQUIRED,
                error_message=f"human takeover required: {challenge.kind.value}",
            )
        verification = await self._verifier(action, state)
        status = {
            VerificationStatus.PASSED: ActionStatus.SUCCEEDED,
            VerificationStatus.FAILED: ActionStatus.FAILED,
            VerificationStatus.AMBIGUOUS: ActionStatus.AMBIGUOUS,
            VerificationStatus.NOT_RUN: ActionStatus.FAILED,
        }[verification.status]
        return ActionResult(
            action_id=action.id,
            status=status,
            verification=verification,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            output=output,
            evidence_ids=[state.screenshot_artifact_id] if state.screenshot_artifact_id else [],
            error_category=(
                ErrorCategory.UNCERTAIN_COMMIT if status == ActionStatus.AMBIGUOUS else None
            ),
        )

    async def _dispatch(self, action: Action, session: BrowserSession) -> dict[str, object]:
        page = session.active_page
        if page is None:
            raise RuntimeError("browser session has no active page")
        if action.kind == ActionKind.NAVIGATE:
            url = str(action.arguments["url"])
            await page.goto(url, wait_until=action.arguments.get("wait_until", "domcontentloaded"))
            return {"url": url}
        locator = self._locator(page, action.target)
        if action.kind == ActionKind.CLICK:
            await locator.click()
        elif action.kind == ActionKind.TYPE:
            await locator.fill(str(action.arguments.get("value", "")))
        elif action.kind == ActionKind.SELECT:
            await locator.select_option(action.arguments.get("value"))
        elif action.kind == ActionKind.UPLOAD:
            await locator.set_input_files(action.arguments.get("files", []))
        elif action.kind == ActionKind.DOWNLOAD:
            save_as = action.arguments.get("save_as")
            if not save_as:
                raise ValueError("download action requires save_as")
            async with page.expect_download() as download_info:
                await locator.click()
            download = await download_info.value
            await download.save_as(str(save_as))
            return {"path": str(save_as), "suggested_filename": download.suggested_filename}
        elif action.kind == ActionKind.EXTRACT:
            return {"text": await locator.text_content()}
        elif action.kind == ActionKind.WAIT:
            milliseconds = int(float(action.arguments.get("seconds", 1)) * 1000)
            await page.wait_for_timeout(milliseconds)
        else:
            raise NotImplementedError(f"action kind {action.kind.value} is not implemented")
        return {"dispatched": True}

    @staticmethod
    def _locator(page, target: dict[str, object]):
        if "role" in target:
            return page.get_by_role(str(target["role"]), name=target.get("name"))
        selector = target.get("selector")
        if not selector:
            raise ValueError("action target requires role or selector")
        return page.locator(str(selector))
