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

from webauto.domain import AgentTaskRequest

from .action_policy import (
    APPROVAL_REQUIRED_MARKER,
    HUMAN_REQUIRED_MARKER,
    click_requires_approval,
    external_write_operation,
    input_requires_human,
)
from .write_grants import BrowserWriteGrantAuthority


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

    def __init__(self, write_grants: BrowserWriteGrantAuthority | None = None) -> None:
        self.write_grants = write_grants or BrowserWriteGrantAuthority()

    def validate_request(self, request: AgentTaskRequest) -> None:
        if not request.read_only or request.budget.max_external_writes:
            try:
                self.write_grants.validate_request(request)
            except PermissionError as exc:
                raise BrowserAgentPolicyViolation(str(exc)) from exc
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

    def assert_navigation(self, url: str, request: AgentTaskRequest) -> None:
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

    def protect_tools(self, tools: Any, request: AgentTaskRequest) -> Any:
        """Wrap navigation and interactive actions at the installed-tool boundary."""

        try:
            actions = tools.registry.registry.actions
            navigate = actions["navigate"]
            original_navigate = navigate.function
        except (AttributeError, KeyError, TypeError) as exc:
            raise BrowserAgentPolicyViolation(
                "Browser Use navigation action cannot be policy-wrapped"
            ) from exc

        async def guarded_navigate(
            *, params: Any, browser_session: Any | None = None, **context: Any
        ) -> Any:
            self.assert_navigation(str(getattr(params, "url", "")), request)
            if browser_session is not None:
                context["browser_session"] = browser_session
            result = original_navigate(params=params, **context)
            return await result if inspect.isawaitable(result) else result

        actions["navigate"] = navigate.model_copy(
            update={
                "function": guarded_navigate,
                "description": navigate.description
                + " WebAuto blocks local/private networks and any URL outside this task scope.",
            }
        )

        click = actions.get("click")
        if click is not None:
            original_click = click.function

            async def guarded_click(*, params: Any, browser_session: Any, **context: Any) -> Any:
                node = await browser_session.get_element_by_index(params.index)
                if node is not None:
                    approval_required, preview = click_requires_approval(node)
                    if approval_required:
                        observed = external_write_operation(preview)
                        if observed == "payment":
                            raise BrowserAgentPolicyViolation(
                                f"{HUMAN_REQUIRED_MARKER}: payment always requires human control"
                            )
                        if observed == "prohibited":
                            raise BrowserAgentPolicyViolation(
                                f"{HUMAN_REQUIRED_MARKER}: this external write is prohibited"
                            )
                        current_url_reader = getattr(browser_session, "get_current_page_url", None)
                        if not callable(current_url_reader):
                            raise BrowserAgentPolicyViolation(
                                f"{APPROVAL_REQUIRED_MARKER}: current page URL cannot be verified at the final write boundary"
                            )
                        current_url = current_url_reader()
                        if inspect.isawaitable(current_url):
                            current_url = await current_url
                        safe_current_url = _safe_approval_url(str(current_url))
                        try:
                            grant = self.write_grants.validate_request(request)
                        except PermissionError as exc:
                            button_text = str(
                                preview.get("text") or preview.get("accessible_name") or ""
                            ).strip()
                            approval_request = {
                                "operation": observed or "unclassified",
                                "button_text": button_text,
                                "target": preview,
                                "current_url": safe_current_url,
                                "page_revision": _approval_page_revision(safe_current_url, preview),
                                "evidence_ids": [safe_current_url] if safe_current_url else [],
                            }
                            raise BrowserAgentPolicyViolation(
                                f"{APPROVAL_REQUIRED_MARKER}: "
                                + json.dumps(
                                    approval_request,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                )
                                + f"; reason={exc}"
                            ) from exc
                        approved_object = request.context["approved_object"]
                        expected_control = str(approved_object.get("final_control") or "")
                        observed_control = " ".join(
                            [
                                str(preview.get("text") or ""),
                                str(preview.get("accessible_name") or ""),
                                *[str(value) for value in preview.get("attributes", {}).values()],
                            ]
                        )
                        if not _control_matches(expected_control, observed_control):
                            raise BrowserAgentPolicyViolation(
                                f"{APPROVAL_REQUIRED_MARKER}: final control differs from approval"
                            )
                        if _canonical_url(str(current_url)) != _canonical_url(grant.source_url):
                            raise BrowserAgentPolicyViolation(
                                f"{APPROVAL_REQUIRED_MARKER}: current page URL differs from approval"
                            )
                        try:
                            self.write_grants.consume(
                                request,
                                observed_operation=observed or grant.operation,
                            )
                        except PermissionError as exc:
                            raise BrowserAgentPolicyViolation(
                                f"{APPROVAL_REQUIRED_MARKER}: {exc}: {preview}"
                            ) from exc
                        result = original_click(
                            params=params,
                            browser_session=browser_session,
                            **context,
                        )
                        return await result if inspect.isawaitable(result) else result
                result = original_click(
                    params=params,
                    browser_session=browser_session,
                    **context,
                )
                return await result if inspect.isawaitable(result) else result

            actions["click"] = click.model_copy(
                update={
                    "function": guarded_click,
                    "description": click.description
                    + " WebAuto blocks purchases, submissions, publishing, messages, deletion "
                    "and other external writes until a bound approval is supplied.",
                }
            )

        input_action = actions.get("input")
        if input_action is not None:
            original_input = input_action.function

            async def guarded_input(*, params: Any, browser_session: Any, **context: Any) -> Any:
                node = await browser_session.get_element_by_index(params.index)
                if node is not None:
                    human_required, preview = input_requires_human(node)
                    if human_required:
                        raise BrowserAgentPolicyViolation(
                            f"{HUMAN_REQUIRED_MARKER}: sensitive input requires human control: {preview}"
                        )
                result = original_input(params=params, browser_session=browser_session, **context)
                return await result if inspect.isawaitable(result) else result

            actions["input"] = input_action.model_copy(
                update={
                    "function": guarded_input,
                    "description": input_action.description
                    + " Password, payment and verification fields require human takeover.",
                }
            )

        upload = actions.get("upload_file")
        if upload is not None:
            original_upload = upload.function

            async def guarded_upload(*, params: Any, browser_session: Any, **context: Any) -> Any:
                try:
                    grant = self.write_grants.validate_request(request)
                except PermissionError as exc:
                    raise BrowserAgentPolicyViolation(str(exc)) from exc
                if grant.operation != "xianyu_publish":
                    raise BrowserAgentPolicyViolation(
                        "file upload is only allowed by an approved Xianyu publish"
                    )
                requested = str(Path(str(getattr(params, "path", ""))).resolve())
                if requested not in grant.file_digests:
                    raise BrowserAgentPolicyViolation(
                        "upload path is outside the signed file grant"
                    )
                result = original_upload(
                    params=params,
                    browser_session=browser_session,
                    **context,
                )
                return await result if inspect.isawaitable(result) else result

            actions["upload_file"] = upload.model_copy(
                update={
                    "function": guarded_upload,
                    "description": upload.description
                    + " WebAuto permits only run-authorized, checksum-bound listing images.",
                }
            )

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
