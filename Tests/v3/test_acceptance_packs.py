"""M8 representative acceptance packs over the shared runtime."""

from pathlib import Path

import pytest

from webauto.agent import CommitGuard, CommitState, GraphExecutor, StepOutcome
from webauto.domain import IdempotencyClass, RiskLevel
from webauto.scenarios import CapabilityMatrix, ListingDraft, ListingPublishPack, ShoppingPack


def test_shopping_pack_filters_and_compares_candidates_without_checkout() -> None:
    pack = ShoppingPack()
    candidates = [
        {"id": "a", "title": "商品 A", "price": 199, "rating": 4.8, "in_stock": True},
        {"id": "b", "title": "商品 B", "price": 260, "rating": 4.9, "in_stock": True},
        {"id": "c", "title": "商品 C", "price": 180, "rating": 4.2, "in_stock": False},
    ]
    result = pack.compare(candidates, max_price=220, min_rating=4.5)
    assert [item["id"] for item in result] == ["a"]
    action = pack.add_to_cart_action("a", approval_id="approval-1")
    assert action.risk_level == RiskLevel.L2
    assert action.approval_id == "approval-1"
    assert action.verifier.expectation["cart_contains"] == "a"


@pytest.mark.asyncio
async def test_shopping_pack_runs_shared_capability_graph() -> None:
    pack = ShoppingPack()
    calls = []

    async def handler(node, context):
        calls.append(node.capability)
        return StepOutcome(output={node.capability: True})

    handlers = {node.capability: handler for node in pack.graph.nodes}
    result = await GraphExecutor(handlers).run("run-shopping", pack.graph, {})
    assert result.succeeded
    assert calls == pack.capabilities


def test_listing_pack_builds_preview_diff_and_guarded_publish_action(tmp_path: Path) -> None:
    image = tmp_path / "item.jpg"
    image.write_bytes(b"fixture-image")
    draft = ListingDraft(
        title="九成新测试商品",
        description="本地验收用商品描述",
        price="99.00",
        category="测试分类",
        condition="九成新",
        image_files=[image],
    )
    pack = ListingPublishPack()
    preview = pack.preview(draft, previous={"price": "109.00"})
    assert preview.diff["price"] == {"before": "109.00", "after": "99.00"}
    action = pack.publish_action(preview, approval_id="approval-1")
    assert action.idempotency == IdempotencyClass.NON_IDEMPOTENT
    assert action.risk_level == RiskLevel.L3
    assert action.verifier.kind == "business_query"

    guard = CommitGuard(action.idempotency, action.approval_id)
    guard.begin_submit()
    guard.mark_transport_unknown()
    assert guard.state == CommitState.VERIFYING_COMMIT


@pytest.mark.asyncio
async def test_listing_pack_pauses_at_publish_without_real_approval() -> None:
    pack = ListingPublishPack()

    async def handler(node, context):
        return StepOutcome(output={node.id: True})

    result = await GraphExecutor({node.capability: handler for node in pack.graph.nodes}).run(
        "run-listing", pack.graph, {}
    )
    assert result.waiting_for_approval
    assert result.failed_node_id == "publish"


def test_capability_matrix_covers_provider_skill_risk_and_verification() -> None:
    matrix = CapabilityMatrix.from_packs([ShoppingPack(), ListingPublishPack()])
    assert matrix.has("web.list.extract", provider="managed", verified=True)
    assert matrix.has("web.file.upload", provider="attach", verified=True)
    assert matrix.has("web.publish.submit", risk=RiskLevel.L3, verified=True)
    assert matrix.uncovered() == ()
