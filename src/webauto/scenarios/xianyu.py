"""Xianyu-specific second-hand risk, inquiry and listing fact boundaries."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class XianyuListingFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    images: list[Path] = Field(min_length=1)
    brand: str | None = None
    model: str | None = None
    condition: str = Field(min_length=1)
    defects: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    purchase_time: str | None = None
    original_price: Decimal | None = Field(default=None, gt=0)
    asking_price: Decimal = Field(gt=0)
    location: str | None = None
    delivery: str = "邮寄"

    @model_validator(mode="after")
    def images_must_exist(self) -> XianyuListingFacts:
        missing = [str(path) for path in self.images if not path.is_file()]
        if missing:
            raise ValueError(f"missing image files: {missing}")
        return self


class XianyuRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    level: str
    flags: list[str]
    questions: list[str]


def assess_second_hand_risk(item: dict[str, object]) -> XianyuRiskAssessment:
    flags: list[str] = []
    questions: list[str] = []
    if (
        item.get("market_price")
        and item.get("price")
        and (Decimal(str(item["price"])) < Decimal(str(item["market_price"])) * Decimal("0.45"))
    ):
        flags.append("异常低价")
    description = str(item.get("description") or "")
    if len(description.strip()) < 20:
        flags.append("描述过短")
    if not item.get("real_photos"):
        flags.append("缺少实拍图")
    if item.get("off_platform_contact"):
        flags.append("引导站外交易")
    for field, question in (
        ("defects", "是否存在功能或外观瑕疵？"),
        ("repair_history", "是否维修或拆机过？"),
        ("accessories", "包含哪些配件？"),
        ("warranty", "是否仍在保修期？"),
    ):
        if not item.get(field):
            questions.append(question)
    level = "high" if "引导站外交易" in flags or len(flags) >= 3 else "medium" if flags else "low"
    return XianyuRiskAssessment(level=level, flags=flags, questions=questions)


def inquiry_draft(item: dict[str, object]) -> list[str]:
    assessment = assess_second_hand_risk(item)
    prefix = f"你好，想咨询一下这件{item.get('title') or '商品'}。"
    return [prefix + question for question in assessment.questions]


def listing_copy(facts: XianyuListingFacts) -> dict[str, object]:
    identity = " ".join(value for value in (facts.brand, facts.model, facts.name) if value)
    title = f"{identity} {facts.condition}"[:30]
    lines = [f"物品：{identity}", f"成色：{facts.condition}"]
    if facts.defects:
        lines.append("瑕疵：" + "；".join(facts.defects))
    else:
        lines.append("瑕疵：请以图片和沟通确认结果为准")
    if facts.accessories:
        lines.append("配件：" + "、".join(facts.accessories))
    if facts.purchase_time:
        lines.append("购买时间：" + facts.purchase_time)
    lines.append(f"交易方式：{facts.delivery}")
    return {"title": title, "description": "\n".join(lines), "price": facts.asking_price}
