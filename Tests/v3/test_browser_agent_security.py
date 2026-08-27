"""Dynamic browser-agent policy, SSRF and redaction tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webauto.agent_backends import (
    BrowserAgentPolicyViolation,
    BrowserAgentSecurityPolicy,
    BrowserUseAdapter,
    SensitiveDataRedactor,
)
from webauto.domain import AgentTaskRequest, Placement


def task(
    *scopes: str,
    unrestricted: bool = False,
    context: dict | None = None,
) -> AgentTaskRequest:
    return AgentTaskRequest(
        run_id="run-security",
        objective="Read the authorized page",
        success_criteria=("Return a sourced result",),
        profile_id="personal",
        placement=Placement.DESKTOP_MANAGED,
        allowed_domains=scopes,
        allow_unrestricted_domains=unrestricted,
        context=context or {},
    )


@pytest.mark.parametrize(
    "scope",
    (
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "localhost",
        "metadata.google.internal",
        "service.internal",
    ),
)
def test_policy_blocks_private_local_and_metadata_scopes(scope: str) -> None:
    with pytest.raises(BrowserAgentPolicyViolation, match="private or local"):
        BrowserAgentSecurityPolicy().validate_request(task(scope))


def test_policy_blocks_unsafe_scheme_cross_domain_and_nonstandard_port() -> None:
    policy = BrowserAgentSecurityPolicy()
    request = task("example.com")
    with pytest.raises(BrowserAgentPolicyViolation, match="HTTP"):
        policy.assert_navigation("file:///etc/passwd", request)
    with pytest.raises(BrowserAgentPolicyViolation, match="outside"):
        policy.assert_navigation("https://example.com.evil.test/", request)
    with pytest.raises(BrowserAgentPolicyViolation, match="port"):
        policy.assert_navigation("https://example.com:8443/", request)


def test_private_network_requires_explicit_scope_and_two_consents() -> None:
    policy = BrowserAgentSecurityPolicy()
    request = task(
        "http://127.0.0.1:8080",
        context={
            "allow_private_network": True,
            "allow_nonstandard_ports": True,
            "urls": ["http://127.0.0.1:8080/fixture"],
        },
    )
    policy.validate_request(request)
    policy.assert_navigation("http://127.0.0.1:8080/fixture/next", request)
    with pytest.raises(BrowserAgentPolicyViolation, match="explicit"):
        policy.validate_request(
            task("*", unrestricted=True, context={"allow_private_network": True})
        )


class _RegisteredAction:
    def __init__(self, function, description="Navigate") -> None:
        self.function = function
        self.description = description

    def model_copy(self, *, update):
        return _RegisteredAction(
            update.get("function", self.function),
            update.get("description", self.description),
        )


@pytest.mark.asyncio
async def test_navigation_is_checked_at_the_final_tool_boundary() -> None:
    calls: list[str] = []

    async def navigate(*, params, **context):
        calls.append(params.url)
        return "ok"

    action = _RegisteredAction(navigate)
    tools = SimpleNamespace(
        registry=SimpleNamespace(registry=SimpleNamespace(actions={"navigate": action}))
    )
    policy = BrowserAgentSecurityPolicy()
    policy.protect_tools(tools, task("example.com"))
    guarded = tools.registry.registry.actions["navigate"].function

    assert await guarded(params=SimpleNamespace(url="https://example.com/item")) == "ok"
    with pytest.raises(BrowserAgentPolicyViolation, match="outside"):
        await guarded(params=SimpleNamespace(url="https://evil.test/"))
    assert calls == ["https://example.com/item"]


def test_sensitive_result_redaction_is_recursive() -> None:
    redacted = SensitiveDataRedactor().redact(
        {
            "password": "plain-text",
            "message": "Authorization: Bearer abc.def.ghi; token=visible-secret",
            "nested": [{"card_number": "4111 1111 1111 1111"}],
        }
    )
    assert redacted["password"] == "[REDACTED]"
    assert "abc.def.ghi" not in redacted["message"]
    assert "visible-secret" not in redacted["message"]
    assert redacted["nested"][0]["card_number"] == "[REDACTED]"


class _SensitiveHistory:
    def __init__(self) -> None:
        self.history = [object()]

    def is_successful(self):
        return False

    def is_validated(self):
        return False

    def urls(self):
        return ["https://example.com/result?token=visible-secret"]

    def errors(self):
        return ["Authorization=Bearer abc.def.ghi"]

    def final_result(self):
        return "API key sk-1234567890abcdefghijkl must not escape"


def test_browser_use_history_is_redacted_before_crossing_adapter_boundary() -> None:
    adapter = BrowserUseAdapter(model_factory=lambda: object(), controlled_tools=object())
    result = adapter._map_history(_SensitiveHistory())
    serialized = result.model_dump_json()
    assert "visible-secret" not in serialized
    assert "abc.def.ghi" not in serialized
    assert "sk-1234567890abcdefghijkl" not in serialized
    assert "[REDACTED]" in serialized
