"""Browser execution modes and session lifecycle boundary."""

from .contracts import (
    BrowserCapabilities,
    BrowserControl,
    BrowserHealth,
    BrowserProvider,
    BrowserSession,
    ControlOwner,
)
from .discovery import discover_browsers
from .executor import ActionExecutor
from .factory import ConfiguredBrowser, configured_browser
from .grounder import GroundingTarget, LocatorCandidate, PageStateGrounder
from .lease import InMemoryLeaseManager, LeaseConflict, ProfileLease
from .lifecycle import PageLifecycle
from .live import LiveBrowserController, LiveState
from .observer import BrowserObserver
from .playwright_provider import BrowserAttachProvider, DesktopManagedProvider
from .rate_limit import RateBudgetExceeded, SiteRateLimiter, SiteRatePolicy
from .reliability import (
    ChallengeDetection,
    ChallengeDetector,
    ChallengeKind,
    DetectionSurfaceProbe,
    DetectionSurfaceReport,
    IdentityDrift,
    LaunchAudit,
    ProfileIdentity,
    ProfileIdentityStore,
    audit_launch_options,
    compare_identity,
)
from .session_bridge import BrowserAgentSessionBridge, BrowserAgentSessionPlan

__all__ = [
    "ActionExecutor",
    "BrowserAgentSessionBridge",
    "BrowserAgentSessionPlan",
    "BrowserAttachProvider",
    "BrowserCapabilities",
    "BrowserControl",
    "BrowserHealth",
    "BrowserObserver",
    "BrowserProvider",
    "BrowserSession",
    "ChallengeDetection",
    "ChallengeDetector",
    "ChallengeKind",
    "ConfiguredBrowser",
    "ControlOwner",
    "DesktopManagedProvider",
    "DetectionSurfaceProbe",
    "DetectionSurfaceReport",
    "GroundingTarget",
    "IdentityDrift",
    "InMemoryLeaseManager",
    "LaunchAudit",
    "LeaseConflict",
    "LiveBrowserController",
    "LiveState",
    "LocatorCandidate",
    "PageLifecycle",
    "PageStateGrounder",
    "ProfileIdentity",
    "ProfileIdentityStore",
    "ProfileLease",
    "RateBudgetExceeded",
    "SiteRateLimiter",
    "SiteRatePolicy",
    "audit_launch_options",
    "compare_identity",
    "configured_browser",
    "discover_browsers",
]
