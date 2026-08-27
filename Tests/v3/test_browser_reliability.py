from pathlib import Path

import pytest

from webauto.domain import PageState
from webauto.runtime.browser import (
    ChallengeDetector,
    ChallengeKind,
    DetectionSurfaceProbe,
    ProfileIdentity,
    ProfileIdentityStore,
    audit_launch_options,
    compare_identity,
)


def identity(**updates):
    values = {
        "browser_family": "chrome",
        "browser_version": "140",
        "platform": "Win32",
        "user_agent": "Chrome/140",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "screen": "1920x1080",
        "device_pixel_ratio": 1.0,
        "headless": False,
    }
    values.update(updates)
    return ProfileIdentity(**values)


def test_profile_identity_is_write_once_and_detects_hard_drift(tmp_path: Path):
    store = ProfileIdentityStore(tmp_path)
    baseline = store.save_once("personal", identity())
    assert store.save_once("personal", identity(screen="800x600")) == baseline
    assert compare_identity(baseline, identity()).compatible
    drift = compare_identity(baseline, identity(timezone="UTC"))
    assert not drift.compatible and drift.changed_fields == ("timezone",)
    with pytest.raises(ValueError):
        store.load("../escape")


class FakePage:
    async def evaluate(self, script):
        return {
            "userAgent": "Mozilla Chrome/140",
            "webdriver": True,
            "platform": "Win32",
            "language": "zh-CN",
            "languages": ["en-US", "zh-CN"],
            "timezone": "Asia/Shanghai",
            "screen": "1920x1080",
            "dpr": 1,
            "chromeObject": True,
            "workerSupported": True,
        }


@pytest.mark.asyncio
async def test_detection_surface_probe_reports_without_spoofing():
    report = await DetectionSurfaceProbe().inspect(
        FakePage(), browser_family="chrome", browser_version="140"
    )
    assert report.webdriver_exposed
    assert "navigator.webdriver is exposed" in report.warnings
    assert "navigator.language differs from languages[0]" in report.warnings


@pytest.mark.parametrize(
    ("state", "kind"),
    [
        (
            PageState(url="https://x.test", dom_snapshot="<h1>请完成滑块验证码</h1>"),
            ChallengeKind.CAPTCHA,
        ),
        (
            PageState(
                url="https://x.test",
                dom_snapshot="normal page content that is long enough",
                network_events=[{"status": 429}],
            ),
            ChallengeKind.RATE_LIMIT,
        ),
        (
            PageState(
                url="https://x.test",
                dom_snapshot="normal page content that is long enough",
                network_events=[{"status": 403}],
            ),
            ChallengeKind.ACCESS_DENIED,
        ),
    ],
)
def test_challenge_detector_classifies_evidence(state, kind):
    result = ChallengeDetector().detect(state)
    assert result.detected and result.kind == kind and result.requires_human


def test_challenge_detector_leaves_normal_page_alone():
    state = PageState(
        url="https://x.test/item",
        dom_snapshot="<html><body>正常商品详情内容足够长，不属于空壳页面。</body></html>",
    )
    assert not ChallengeDetector().detect(state).detected


def test_launch_option_audit_flags_identity_and_trust_risks():
    clean = audit_launch_options({"headless": False, "args": ["--start-maximized"]})
    assert clean.acceptable
    risky = audit_launch_options(
        {
            "headless": True,
            "ignore_https_errors": True,
            "args": ["--disable-web-security", "--proxy-server=http://127.0.0.1:8888"],
        }
    )
    assert not risky.acceptable
    assert len(risky.warnings) == 4
