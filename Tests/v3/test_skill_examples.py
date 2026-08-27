"""Example skills, sandbox and generated-candidate tests."""

import json
from pathlib import Path

import pytest

from webauto.site_skills import SkillCandidateBuilder, SkillLoader, SkillSandbox, replay_fixture

EXAMPLES = Path(__file__).parents[2] / "src/webauto/site_skills/examples"


@pytest.mark.parametrize("name", ["list_detail", "complex_form"])
def test_example_skill_loads_and_replays_fixture(name: str) -> None:
    loaded = SkillLoader().load(EXAMPLES / name)
    for fixture_path in loaded.manifest.fixtures:
        fixture = json.loads((loaded.root / fixture_path).read_text(encoding="utf-8"))
        assert replay_fixture(loaded.manifest, fixture).passed


def test_third_scenario_requires_only_new_skill_manifest() -> None:
    appointment = {
        "schema_version": "1.0",
        "site": "booking.example.test",
        "version": "1.0.0",
        "pages": {"calendar": {"url_patterns": ["https://booking.example.test/calendar*"]}},
        "capabilities": {
            "web.slot.inspect": {
                "page": "calendar",
                "preconditions": ["calendar_visible"],
                "actions": [{"kind": "extract", "target": {"selector": "[data-slot]"}}],
                "verifier": {"kind": "page_state", "expectation": {"url_contains": "/calendar"}},
                "recovery": ["reground", "human_takeover"],
            }
        },
        "landmarks": {},
        "fixtures": ["fixtures/calendar.json"],
    }
    loaded = SkillLoader().load_dict(appointment)
    assert loaded.manifest.site == "booking.example.test"


def test_skill_sandbox_rejects_secret_and_arbitrary_script_fields() -> None:
    sandbox = SkillSandbox()
    with pytest.raises(ValueError, match="secret"):
        sandbox.validate_payload({"arguments": {"cookie": "session=abc"}})
    with pytest.raises(ValueError, match="script"):
        sandbox.validate_payload({"actions": [{"kind": "evaluate", "script": "fetch('/admin')"}]})


def test_successful_trace_builds_quarantined_candidate_not_auto_published() -> None:
    source = json.loads((EXAMPLES / "list_detail/skill.json").read_text(encoding="utf-8"))
    candidate = SkillCandidateBuilder().build(
        manifest_payload=source,
        trace_id="trace-1",
        fixture_results=[True, True],
    )
    assert candidate.trace_id == "trace-1"
    assert candidate.fixture_pass_rate == 1.0
    assert candidate.requires_review


def test_builtin_xianyu_skill_is_loadable_and_all_fixtures_replay() -> None:
    import json
    from pathlib import Path

    from webauto.site_skills import SkillLoader, replay_fixture

    root = Path(__file__).parents[2] / "src/webauto/site_skills/builtin/xianyu"
    loaded = SkillLoader().load(root)
    assert loaded.manifest.site == "www.goofish.com"
    assert loaded.manifest.landmarks["publish_button"].confidence < 0.5
    for relative in loaded.manifest.fixtures:
        fixture = json.loads((root / relative).read_text(encoding="utf-8"))
        assert replay_fixture(loaded.manifest, fixture).passed
