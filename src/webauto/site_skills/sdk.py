"""Loader, classifier, replay and immutable skill registry."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from webauto.domain import PageState

from .models import ActionTemplate, SkillManifest


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    manifest: SkillManifest
    digest: str
    root: Path | None = None


class SkillLoader:
    def load(self, root: Path) -> LoadedSkill:
        path = root / "skill.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        loaded = self.load_dict(payload)
        return LoadedSkill(loaded.manifest, loaded.digest, root.resolve())

    def load_dict(self, payload: dict[str, Any]) -> LoadedSkill:
        manifest = SkillManifest.model_validate(payload)
        canonical = json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return LoadedSkill(manifest, digest)


@dataclass(frozen=True, slots=True)
class PageMatch:
    page: str
    confidence: float
    evidence: tuple[str, ...]


class PageClassifier:
    def classify(self, manifest: SkillManifest, state: PageState) -> PageMatch:
        matches: list[PageMatch] = []
        a11y = str(state.accessibility_snapshot or "")
        dom = state.dom_snapshot or ""
        visual = str(state.browser_state.get("visual_signatures", []))
        for name, definition in manifest.pages.items():
            evidence: list[str] = []
            if any(fnmatch.fnmatch(state.url, pattern) for pattern in definition.url_patterns):
                evidence.append("url")
            if definition.dom_markers and all(marker in dom for marker in definition.dom_markers):
                evidence.append("dom")
            if definition.a11y_markers and all(
                marker in a11y for marker in definition.a11y_markers
            ):
                evidence.append("a11y")
            if definition.visual_signatures and all(
                marker in visual for marker in definition.visual_signatures
            ):
                evidence.append("visual")
            possible = sum(
                bool(group)
                for group in (
                    definition.url_patterns,
                    definition.dom_markers,
                    definition.a11y_markers,
                    definition.visual_signatures,
                )
            )
            confidence = len(evidence) / possible if possible else 0
            if evidence:
                matches.append(PageMatch(name, confidence, tuple(evidence)))
        if not matches:
            raise LookupError("page does not match this skill")
        return max(matches, key=lambda item: item.confidence)


_VARIABLE = re.compile(r"^\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}$")


def _render(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = _VARIABLE.fullmatch(value)
        if not match:
            return value
        current: Any = variables
        for part in match.group(1).split("."):
            if not isinstance(current, dict) or part not in current:
                raise KeyError(match.group(1))
            current = current[part]
        return current
    if isinstance(value, dict):
        return {key: _render(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, variables) for item in value]
    return value


def render_action_template(template: ActionTemplate, variables: dict[str, Any]) -> ActionTemplate:
    return ActionTemplate(
        kind=template.kind,
        target=_render(template.target, variables),
        arguments=_render(template.arguments, variables),
    )


@dataclass(frozen=True, slots=True)
class FixtureReplayResult:
    passed: bool
    page: str
    verification_summary: str


def replay_fixture(manifest: SkillManifest, fixture: dict[str, Any]) -> FixtureReplayResult:
    state = PageState.model_validate(fixture["page_state"])
    match = PageClassifier().classify(manifest, state)
    capability = manifest.capabilities[fixture["capability"]]
    expected_page = fixture["expected_page"]
    if match.page != expected_page or capability.page != expected_page:
        return FixtureReplayResult(False, match.page, "page classification mismatch")
    checks: list[bool] = []
    expectation = capability.verifier.expectation
    if "dom_contains" in expectation:
        checks.append(str(expectation["dom_contains"]) in (state.dom_snapshot or ""))
    if "url_contains" in expectation:
        checks.append(str(expectation["url_contains"]) in state.url)
    passed = bool(checks) and all(checks)
    return FixtureReplayResult(passed, match.page, "passed" if passed else "verifier failed")


class SkillState(str, Enum):
    STABLE = "stable"
    CANARY = "canary"
    QUARANTINED = "quarantined"


@dataclass(slots=True)
class _PublishedSkill:
    skill: LoadedSkill
    state: SkillState
    reason: str | None = None


class SkillRegistry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], _PublishedSkill] = {}

    def publish(self, skill: LoadedSkill, *, state: SkillState) -> None:
        key = (skill.manifest.site, skill.manifest.version)
        existing = self._items.get(key)
        if existing and existing.skill.digest != skill.digest:
            raise ValueError("published skill versions are immutable")
        self._items[key] = _PublishedSkill(skill, state)

    def resolve(
        self, site: str, *, run_id: str | None = None, version: str | None = None
    ) -> LoadedSkill:
        if version is not None:
            published = self._items[(site, version)]
            if published.state == SkillState.QUARANTINED:
                raise ValueError(f"skill is quarantined: {published.reason}")
            return published.skill
        stable = [
            item.skill
            for (item_site, _), item in self._items.items()
            if item_site == site and item.state == SkillState.STABLE
        ]
        if not stable:
            raise KeyError(f"no stable skill for {site}")
        return max(stable, key=lambda skill: tuple(map(int, skill.manifest.version.split("."))))

    def quarantine(self, site: str, version: str, *, reason: str) -> None:
        published = self._items[(site, version)]
        published.state = SkillState.QUARANTINED
        published.reason = reason

    def rollback(self, site: str) -> LoadedSkill:
        return self.resolve(site, run_id="rollback")
