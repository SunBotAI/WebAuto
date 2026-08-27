"""Identity consistency, automation-surface diagnostics and challenge detection."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from webauto.domain import PageState


@dataclass(frozen=True, slots=True)
class ProfileIdentity:
    browser_family: str
    browser_version: str
    platform: str
    user_agent: str
    language: str
    timezone: str
    screen: str
    device_pixel_ratio: float
    headless: bool


@dataclass(frozen=True, slots=True)
class IdentityDrift:
    compatible: bool
    changed_fields: tuple[str, ...] = ()
    summary: str = "identity is stable"


class ProfileIdentityStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, profile_id: str) -> Path:
        if not profile_id or any(part in profile_id for part in ("/", "\\", "..")):
            raise ValueError("profile_id must be a simple identifier")
        return self._root / f"{profile_id}.identity.json"

    def load(self, profile_id: str) -> ProfileIdentity | None:
        path = self._path(profile_id)
        return (
            ProfileIdentity(**json.loads(path.read_text(encoding="utf-8")))
            if path.exists()
            else None
        )

    def save_once(self, profile_id: str, identity: ProfileIdentity) -> ProfileIdentity:
        existing = self.load(profile_id)
        if existing is not None:
            return existing
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(profile_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(identity), indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)
        return identity


_HARD_IDENTITY_FIELDS = (
    "browser_family",
    "platform",
    "user_agent",
    "language",
    "timezone",
    "screen",
    "headless",
)


def compare_identity(baseline: ProfileIdentity, observed: ProfileIdentity) -> IdentityDrift:
    changed = tuple(
        name for name in _HARD_IDENTITY_FIELDS if getattr(baseline, name) != getattr(observed, name)
    )
    return (
        IdentityDrift(False, changed, "identity drift: " + ", ".join(changed))
        if changed
        else IdentityDrift(True)
    )


@dataclass(frozen=True, slots=True)
class DetectionSurfaceReport:
    identity: ProfileIdentity
    webdriver_exposed: bool
    chrome_object_present: bool
    languages: tuple[str, ...]
    worker_supported: bool
    warnings: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class DetectionSurfaceProbe:
    """Inspect browser consistency; never changes or spoofs page APIs."""

    _SCRIPT = """async () => ({userAgent:navigator.userAgent,webdriver:navigator.webdriver===true,platform:navigator.platform||'',language:navigator.language||'',languages:Array.from(navigator.languages||[]),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'',screen:`${screen.width}x${screen.height}`,dpr:window.devicePixelRatio||1,chromeObject:typeof window.chrome==='object',workerSupported:typeof Worker!=='undefined'})"""

    async def inspect(
        self, page: Any, *, browser_family: str, browser_version: str
    ) -> DetectionSurfaceReport:
        raw = await page.evaluate(self._SCRIPT)
        ua = str(raw.get("userAgent", ""))
        identity = ProfileIdentity(
            browser_family,
            browser_version,
            str(raw.get("platform", "")),
            ua,
            str(raw.get("language", "")),
            str(raw.get("timezone", "")),
            str(raw.get("screen", "")),
            float(raw.get("dpr", 1)),
            "HeadlessChrome" in ua,
        )
        warnings: list[str] = []
        if raw.get("webdriver") is True:
            warnings.append("navigator.webdriver is exposed")
        if identity.language and raw.get("languages") and identity.language != raw["languages"][0]:
            warnings.append("navigator.language differs from languages[0]")
        if browser_family.lower() in {"chrome", "edge", "chromium"} and not raw.get("chromeObject"):
            warnings.append("Chromium identity has no window.chrome object")
        return DetectionSurfaceReport(
            identity,
            bool(raw.get("webdriver")),
            bool(raw.get("chromeObject")),
            tuple(str(x) for x in raw.get("languages", [])),
            bool(raw.get("workerSupported")),
            tuple(warnings),
            dict(raw),
        )


class ChallengeKind(str, Enum):
    CAPTCHA = "captcha"
    LOGIN = "login"
    SECURITY_CHECK = "security_check"
    RATE_LIMIT = "rate_limit"
    ACCESS_DENIED = "access_denied"
    EMPTY_SHELL = "empty_shell"


@dataclass(frozen=True, slots=True)
class ChallengeDetection:
    detected: bool
    kind: ChallengeKind | None = None
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    requires_human: bool = False


class ChallengeDetector:
    _MARKERS: ClassVar[dict[ChallengeKind, tuple[str, ...]]] = {
        ChallengeKind.CAPTCHA: ("验证码", "滑块", "captcha", "robot check", "人机验证"),
        ChallengeKind.LOGIN: ("扫码登录", "请登录", "重新登录", "login required"),
        ChallengeKind.SECURITY_CHECK: ("安全验证", "设备验证", "异常访问", "security check"),
        ChallengeKind.RATE_LIMIT: ("访问频繁", "操作频繁", "稍后再试", "too many requests"),
        ChallengeKind.ACCESS_DENIED: ("拒绝访问", "access denied", "forbidden"),
    }

    def detect(self, state: PageState) -> ChallengeDetection:
        text = " ".join(
            (
                state.title,
                state.url,
                state.dom_snapshot or "",
                str(state.accessibility_snapshot or ""),
            )
        ).lower()
        codes = {
            int(e["status"]) for e in state.network_events if str(e.get("status", "")).isdigit()
        }
        if 429 in codes:
            return ChallengeDetection(True, ChallengeKind.RATE_LIMIT, 1.0, ("http:429",), True)
        if 403 in codes:
            return ChallengeDetection(True, ChallengeKind.ACCESS_DENIED, 0.95, ("http:403",), True)
        for kind, markers in self._MARKERS.items():
            matched = tuple(marker for marker in markers if marker in text)
            if matched:
                return ChallengeDetection(
                    True, kind, min(1.0, 0.65 + 0.1 * len(matched)), matched, True
                )
        if state.dom_snapshot is not None and len(state.dom_snapshot.strip()) < 40:
            return ChallengeDetection(
                True, ChallengeKind.EMPTY_SHELL, 0.6, ("dom:nearly-empty",), False
            )
        return ChallengeDetection(False)


_SUSPICIOUS_LAUNCH_ARGUMENTS = (
    "--disable-web-security",
    "--ignore-certificate-errors",
    "--no-sandbox",
    "--disable-site-isolation-trials",
    "--proxy-server",
)


@dataclass(frozen=True, slots=True)
class LaunchAudit:
    acceptable: bool
    warnings: tuple[str, ...] = ()


def audit_launch_options(options: dict[str, Any]) -> LaunchAudit:
    warnings: list[str] = []
    if options.get("headless") is True:
        warnings.append("headless mode is not recommended for a personal authenticated profile")
    for argument in options.get("args", []) or []:
        name = str(argument).split("=", 1)[0]
        if name in _SUSPICIOUS_LAUNCH_ARGUMENTS:
            warnings.append(f"suspicious launch argument: {name}")
    if options.get("ignore_https_errors"):
        warnings.append("ignore_https_errors weakens browser trust checks")
    return LaunchAudit(not warnings, tuple(warnings))
