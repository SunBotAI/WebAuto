"""Personal shopping normalization and Xianyu safety-domain tests."""

from decimal import Decimal
from pathlib import Path

from webauto.scenarios import (
    ProductCandidate,
    ShoppingAdvisor,
    ShoppingRequest,
    XianyuListingFacts,
    assess_second_hand_risk,
    deduplicate_products,
    inquiry_draft,
    listing_copy,
)


def product(item_id: str, *, price: str, shipping: str = "0", **changes):
    values = {
        "platform": "jd",
        "item_id": item_id,
        "title": "27 英寸 4K 显示器",
        "url": f"https://example.com/{item_id}",
        "price": Decimal(price),
        "shipping": Decimal(shipping),
        "in_stock": True,
        "seller_score": 0.9,
        "specs": {"size": "27", "resolution": "4k"},
        "evidence": {"price": "page"},
    }
    values.update(changes)
    return ProductCandidate(**values)


def test_shopping_ranking_includes_shipping_and_hard_specs() -> None:
    request = ShoppingRequest(
        query="显示器", budget=Decimal(3000), required_specs={"resolution": "4k"}
    )
    ranked = ShoppingAdvisor().rank(
        request,
        [
            product("a", price="2899", shipping="150"),
            product("b", price="2950", shipping="0"),
            product("c", price="2000", specs={"resolution": "2k"}),
        ],
    )
    assert ranked[0].product.item_id == "b"
    assert ranked[0].eligible is True
    assert {item.product.item_id for item in ranked if not item.eligible} == {"a", "c"}


def test_product_deduplication_keeps_candidate_with_more_evidence() -> None:
    sparse = product("same", price="100")
    rich = sparse.model_copy(update={"evidence": {"price": "page", "stock": "page"}})
    assert deduplicate_products([sparse, rich]) == [rich]


def test_xianyu_risk_and_inquiry_do_not_claim_safety() -> None:
    item = {
        "title": "二手相机",
        "price": 500,
        "market_price": 3000,
        "description": "便宜出",
        "real_photos": False,
        "off_platform_contact": True,
    }
    assessment = assess_second_hand_risk(item)
    assert assessment.level == "high"
    assert {"异常低价", "描述过短", "缺少实拍图", "引导站外交易"} <= set(assessment.flags)
    drafts = inquiry_draft(item)
    assert any("维修" in message for message in drafts)
    assert all("安全" not in message for message in drafts)


def test_listing_copy_uses_only_user_supplied_facts(tmp_path: Path) -> None:
    image = tmp_path / "item.jpg"
    image.write_bytes(b"image")
    facts = XianyuListingFacts(
        name="耳机",
        brand="Sony",
        model="XM5",
        images=[image],
        condition="九成新",
        defects=["左侧有轻微划痕"],
        accessories=["收纳盒"],
        asking_price=Decimal(1299),
    )
    copy = listing_copy(facts)
    assert copy["title"] == "Sony XM5 耳机 九成新"
    assert "左侧有轻微划痕" in copy["description"]
    assert "保修" not in copy["description"]
    assert copy["price"] == Decimal(1299)
