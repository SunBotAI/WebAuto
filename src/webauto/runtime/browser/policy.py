"""Security policy enforced around every dynamic browser-agent run."""

from __future__ import annotations

import fnmatch
import hashlib
import inspect
import ipaddress
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urldefrag, urlencode, urlparse, urlunparse

from webauto.runtime.browser.action_policy import (
    APPROVAL_REQUIRED_MARKER,
    HUMAN_REQUIRED_MARKER,
    click_requires_approval,
    external_write_operation,
    input_requires_human,
)


class BrowserAgentPolicyViolation(RuntimeError):
    """A requested browser capability is outside the granted task authority."""


class BrowserAgentSecurityPolicy:
    """Validate task scope and wrap navigation at the final tool boundary."""

    _blocked_hostnames = frozenset(
        {
            "localhost",
            "metadata.google.internal",
            "metadata.google.internal.",
            "instance-data",
            "instance-data.ec2.internal",
        }
    )

    def __init__(self) -> None:
        # B4-01b: write_grants Authority was deleted with the Browser Use
        # stack; grant validation is now part of mcp_browser.GovernedActions
        # (see approval.object_digest binding). Keep the constructor
        # signature-free for backward compatibility with any caller.
        pass

    def validate_request(self, request: Any) -> None:
        # B4-01b: grant validation was removed with the Browser Use stack.
        # Only domain-scope and private-network checks remain.
        private_allowed = bool(request.context.get("allow_private_network"))
        if private_allowed and "*" in request.allowed_domains:
            raise BrowserAgentPolicyViolation(
                "private-network access requires an explicit hostname or URL scope"
            )
        for scope in request.allowed_domains:
            if scope == "*":
                continue
            parsed = urlparse(scope if "://" in scope else "https://" + scope.removeprefix("*."))
            host = parsed.hostname or ""
            if self._is_private_or_local(host) and not private_allowed:
                raise BrowserAgentPolicyViolation(
                    f"private or local browser scope is blocked: {host}"
                )
        for value in request.context.get("urls", []):
            self.assert_navigation(str(value), request)

    def assert_navigation(self, url: str, request: Any) -> None:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise BrowserAgentPolicyViolation("only HTTP(S) browser navigation is allowed")
        if parsed.username or parsed.password:
            raise BrowserAgentPolicyViolation("URLs containing credentials are blocked")
        host = parsed.hostname
        private_allowed = bool(request.context.get("allow_private_network"))
        if self._is_private_or_local(host) and not private_allowed:
            raise BrowserAgentPolicyViolation(
                f"private, loopback, link-local or metadata navigation is blocked: {host}"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise BrowserAgentPolicyViolation("navigation URL contains an invalid port") from exc
        if port not in {None, 80, 443} and not request.context.get("allow_nonstandard_ports"):
            raise BrowserAgentPolicyViolation(f"non-standard browser port is blocked: {port}")
        if not _url_in_scope(url, request.allowed_domains, request.allow_unrestricted_domains):
            raise BrowserAgentPolicyViolation(
                f"navigation is outside the approved domain scope: {parsed.scheme}://{host}"
            )

    def protect_tools(self, tools: Any, request: Any) -> Any:
        """B4-01b stub: Browser Use tool wrapping was removed with that stack."""
        return tools


    def _is_private_or_local(self, hostname: str) -> bool:
        host = hostname.rstrip(".").lower()
        if host in self._blocked_hostnames or host.endswith((".localhost", ".local", ".internal")):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return bool(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )


class SensitiveDataRedactor:
    """Conservatively redact secrets and payment data from results and logs."""

    replacement = "[REDACTED]"
    _sensitive_keys = frozenset(
        {
            "authorization",
            "cookie",
            "set-cookie",
            "password",
            "passwd",
            "secret",
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "token",
            "card_number",
            "cvv",
            "cvc",
        }
    )
    _patterns = (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/]+=*"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        re.compile(
            r"(?i)\b(authorization|cookie|set-cookie|password|passwd|api[_-]?key|"
            r"access[_-]?token|refresh[_-]?token|token|secret)\s*([:=])\s*([^\s,;]+)"
        ),
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
    )

    def redact(self, value: Any, *, key: str | None = None) -> Any:
        if key and key.lower() in self._sensitive_keys:
            return self.replacement
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {
                item_key: self.redact(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        return value

    def redact_text(self, value: str) -> str:
        result = value
        for pattern in self._patterns:
            if pattern.groups >= 3:
                result = pattern.sub(
                    lambda match: f"{match.group(1)}{match.group(2)}{self.replacement}",
                    result,
                )
            else:
                result = pattern.sub(self.replacement, result)
        return result


def _safe_approval_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    blocked = {"token", "session", "sid", "auth", "signature", "sign", "code"}
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in blocked
        ],
        doseq=True,
    )
    return urlunparse(parsed._replace(query=query, fragment=""))


def _approval_page_revision(url: str, preview: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"url": url, "target": preview},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_url(value: str) -> str:
    parsed = urlparse(urldefrag(value.strip())[0])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return parsed.geturl().rstrip("/")


def _control_matches(expected: str, observed: str) -> bool:
    normalize = lambda value: "".join(value.casefold().split())
    expected_value = normalize(expected)
    observed_value = normalize(observed)
    return bool(
        expected_value
        and observed_value
        and (expected_value in observed_value or observed_value in expected_value)
    )


def _url_in_scope(
    url: str,
    scopes: tuple[str, ...],
    unrestricted: bool,
) -> bool:
    if unrestricted and "*" in scopes:
        return True
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for scope in scopes:
        if "://" in scope:
            allowed = urlparse(scope)
            same_origin = (
                parsed.scheme.lower() == allowed.scheme.lower()
                and host == (allowed.hostname or "").lower()
                and parsed.port == allowed.port
            )
            prefix = allowed.path.rstrip("/")
            if same_origin and (
                not prefix or parsed.path == prefix or parsed.path.startswith(prefix + "/")
            ):
                return True
        elif scope.startswith("*."):
            root = scope[2:].lower()
            if host == root or host.endswith("." + root):
                return True
        elif host == scope.lower() or fnmatch.fnmatch(host, scope.lower()):
            return True
    return False
