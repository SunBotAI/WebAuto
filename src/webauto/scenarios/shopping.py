"""Platform-neutral personal-shopping requirements, normalization and ranking."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field


class ShoppingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: str = Field(min_length=1)
    budget: Decimal | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, ge=1)
    required_specs: dict[str, str] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    excluded_terms: list[str] = Field(default_factory=list)
    allow_used: bool = True
    read_only: bool = True


class ProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    platform: str
    item_id: str
    title: str
    url: HttpUrl
    price: Decimal = Field(ge=0)
    shipping: Decimal = Field(default=Decimal(0), ge=0)
    quantity: int = Field(default=1, ge=1)
    condition: str = "unknown"
    in_stock: bool | None = None
    seller: str | None = None
    seller_score: float | None = Field(default=None, ge=0, le=1)
    specs: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def total_price(self) -> Decimal:
        return self.price * self.quantity + self.shipping


class RankedProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product: ProductCandidate
    eligible: bool
    score: float
    reasons: list[str]


class ShoppingAdvisor:
    def rank(
        self, request: ShoppingRequest, candidates: list[ProductCandidate]
    ) -> list[RankedProduct]:
        ranked: list[RankedProduct] = []
        excluded = tuple(value.lower() for value in request.excluded_terms)
        for item in candidates:
            reasons: list[str] = []
            eligible = True
            if item.in_stock is False:
                eligible = False
                reasons.append("out of stock")
            if request.budget is not None and item.total_price > request.budget:
                eligible = False
                reasons.append("over budget")
            if not request.allow_used and item.condition not in {"new", "新品"}:
                eligible = False
                reasons.append("used item excluded")
            if any(term in item.title.lower() for term in excluded):
                eligible = False
                reasons.append("excluded term")
            for key, value in request.required_specs.items():
                if item.specs.get(key) != value:
                    eligible = False
                    reasons.append(f"spec mismatch: {key}")
            price_component = 0.0
            if request.budget and request.budget > 0:
                price_component = max(0.0, 1.0 - float(item.total_price / request.budget))
            trust = item.seller_score if item.seller_score is not None else 0.5
            risk_penalty = min(len(item.risk_flags) * 0.12, 0.6)
            score = (
                price_component * 0.55 + trust * 0.35 + (0.1 if item.in_stock else 0) - risk_penalty
            )
            if eligible:
                reasons.extend(["constraints satisfied", "shipping included in total"])
            ranked.append(
                RankedProduct(product=item, eligible=eligible, score=score, reasons=reasons)
            )
        return sorted(ranked, key=lambda item: (item.eligible, item.score), reverse=True)


def deduplicate_products(candidates: list[ProductCandidate]) -> list[ProductCandidate]:
    unique: dict[tuple[str, str], ProductCandidate] = {}
    for candidate in candidates:
        key = (candidate.platform.lower(), candidate.item_id)
        previous = unique.get(key)
        if previous is None or len(candidate.evidence) > len(previous.evidence):
            unique[key] = candidate
    return list(unique.values())
