"""Versioned declarative Site Skill SDK tests."""

import json
from pathlib import Path

import pytest

from webauto.domain import PageState
from webauto.site_skills import (
    PageClassifier,
    SkillLoader,
    SkillRegistry,
    SkillState,
    render_action_template,
    replay_fixture,
)


def manifest() -> dict:
    return {
        "schema_version": "1.0",
        "site": "example.test",
        "version": "1.2.0",
        "pages": {
            "detail": {
                "url_patterns": ["https://example.test/item/*"],
                "dom_markers": ["data-page=detail"],
                "a11y_markers": ["商品详情"],
            }
        },
        "capabilities": {
            "web.form.fill": {
                "page": "detail",
                "preconditions": ["authorized"],
                "actions": [
                    {
                        "kind": "type",
                        "target": {"landmark": "title"},
                        "arguments": {"value": "{{ title }}"},
                    }
                ],
                "verifier": {"kind": "page_state", "expectation": {"dom_contains": "已保存"}},
                "recovery": ["reground", "human_takeover"],
            }
        },
        "landmarks": {"title": {"selector": "input[name=title]", "confidence": 0.98}},
        "fixtures": ["fixtures/detail.json"],
    }


def test_loader_reads_manifest_and_computes_immutable_digest(tmp_path: Path) -> None:
    skill_dir = tmp_path / "example"
    skill_dir.mkdir()
    (skill_dir / "skill.json").write_text(
        json.dumps(manifest(), ensure_ascii=False), encoding="utf-8"
    )
    loaded = SkillLoader().load(skill_dir)
    assert loaded.manifest.site == "example.test"
    assert loaded.digest.startswith("sha256:")
    assert loaded.manifest.capabilities["web.form.fill"].actions[0].kind == "type"


def test_loader_rejects_executable_script_escape_hatch(tmp_path: Path) -> None:
    payload = manifest()
    payload["script"] = "import os"
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "skill.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        SkillLoader().load(skill_dir)


def test_page_classifier_uses_url_dom_and_a11y_evidence() -> None:
    loaded = SkillLoader().load_dict(manifest())
    state = PageState(
        url="https://example.test/item/1",
        dom_snapshot="<main data-page=detail></main>",
        accessibility_snapshot={"snapshot": "商品详情"},
    )
    match = PageClassifier().classify(loaded.manifest, state)
    assert match.page == "detail"
    assert match.confidence == 1.0
    assert set(match.evidence) == {"url", "dom", "a11y"}


def test_action_template_only_substitutes_declared_values() -> None:
    loaded = SkillLoader().load_dict(manifest())
    template = loaded.manifest.capabilities["web.form.fill"].actions[0]
    rendered = render_action_template(template, {"title": "正常标题"})
    assert rendered.arguments["value"] == "正常标题"
    with pytest.raises(KeyError):
        render_action_template(template, {})


def test_fixture_replay_runs_classifier_and_verifier() -> None:
    loaded = SkillLoader().load_dict(manifest())
    fixture = {
        "page_state": {
            "url": "https://example.test/item/1",
            "dom_snapshot": "<main data-page=detail>已保存</main>",
            "accessibility_snapshot": {"snapshot": "商品详情"},
        },
        "expected_page": "detail",
        "capability": "web.form.fill",
    }
    result = replay_fixture(loaded.manifest, fixture)
    assert result.passed


def test_registry_pins_versions_and_supports_canary_quarantine_rollback() -> None:
    registry = SkillRegistry()
    v1 = SkillLoader().load_dict(manifest())
    v2_payload = manifest()
    v2_payload["version"] = "1.3.0"
    v2 = SkillLoader().load_dict(v2_payload)
    registry.publish(v1, state=SkillState.STABLE)
    registry.publish(v2, state=SkillState.CANARY)
    assert registry.resolve("example.test", run_id="stable-run").manifest.version == "1.2.0"
    assert registry.resolve("example.test", version="1.3.0").manifest.version == "1.3.0"
    registry.quarantine("example.test", "1.3.0", reason="fixture regression")
    with pytest.raises(ValueError, match="quarantined"):
        registry.resolve("example.test", version="1.3.0")
    assert registry.rollback("example.test").manifest.version == "1.2.0"
