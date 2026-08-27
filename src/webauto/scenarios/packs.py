"""Replaceable representative acceptance packs built on shared contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from webauto.domain import (
    Action,
    ActionKind,
    CapabilityGraph,
    CapabilityNode,
    GraphEdge,
    IdempotencyClass,
    RiskLevel,
    VerifierSpec,
)


def _linear_graph(nodes: list[CapabilityNode]) -> CapabilityGraph:
    return CapabilityGraph(
        entry_node_id=nodes[0].id,
        nodes=nodes,
        edges=[GraphEdge(source=left.id, target=right.id) for left, right in pairwise(nodes)],
        max_total_steps=max(10, len(nodes) * 2),
    )


class ShoppingPack:
    name = "shopping"
    capabilities: ClassVar[list[str]] = [
        "web.browse",
        "web.list.extract",
        "web.normalize",
        "web.compare",
    ]

    def __init__(self) -> None:
        self.graph = _linear_graph(
            [
                CapabilityNode(id=f"step-{index}", capability=name)
                for index, name in enumerate(self.capabilities, 1)
            ]
        )

    def compare(
        self,
        candidates: list[dict[str, Any]],
        *,
        max_price: float,
        min_rating: float,
    ) -> list[dict[str, Any]]:
        eligible = [
            item
            for item in candidates
            if item.get("in_stock")
            and float(item["price"]) <= max_price
            and float(item.get("rating", 0)) >= min_rating
        ]
        return sorted(eligible, key=lambda item: (float(item["price"]), -float(item["rating"])))

    def add_to_cart_action(self, item_id: str, *, approval_id: str) -> Action:
        return Action(
            kind=ActionKind.CLICK,
            target={"landmark": "add_to_cart", "item_id": item_id},
            arguments={"item_id": item_id},
            preconditions=["item_and_variant_confirmed", "cart_write_approved"],
            expected_effect={"cart_contains": item_id},
            risk_level=RiskLevel.L2,
            idempotency=IdempotencyClass.IDEMPOTENT,
            verifier=VerifierSpec(kind="business_query", expectation={"cart_contains": item_id}),
            approval_id=approval_id,
        )


class ListingDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=5)
    price: Decimal = Field(gt=0)
    category: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    image_files: list[Path] = Field(min_length=1)

    @field_validator("image_files")
    @classmethod
    def images_exist(cls, values: list[Path]) -> list[Path]:
        missing = [str(path) for path in values if not path.is_file()]
        if missing:
            raise ValueError(f"missing image files: {missing}")
        return values


@dataclass(frozen=True, slots=True)
class ListingPreview:
    draft: ListingDraft
    diff: dict[str, dict[str, Any]]
    digest: str


class ListingPublishPack:
    name = "listing_publish"
    capabilities: ClassVar[list[str]] = [
        "web.image.inspect",
        "web.file.upload",
        "web.complex_form.fill",
        "web.preview.verify",
        "web.publish.submit",
    ]

    def __init__(self) -> None:
        nodes = [
            CapabilityNode(id="inspect", capability="web.image.inspect"),
            CapabilityNode(id="upload", capability="web.file.upload"),
            CapabilityNode(id="fill", capability="web.complex_form.fill"),
            CapabilityNode(id="preview", capability="web.preview.verify"),
            CapabilityNode(
                id="publish",
                capability="web.publish.submit",
                approval_required=True,
                max_attempts=1,
            ),
        ]
        self.graph = _linear_graph(nodes)

    def preview(self, draft: ListingDraft, *, previous: dict[str, Any]) -> ListingPreview:
        current = draft.model_dump(mode="json")
        diff = {
            key: {"before": previous.get(key), "after": value}
            for key, value in current.items()
            if key != "image_files" and previous.get(key) != value
        }
        canonical = json.dumps(current, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return ListingPreview(
            draft, diff, "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        )

    def publish_action(self, preview: ListingPreview, *, approval_id: str) -> Action:
        return Action(
            kind=ActionKind.CLICK,
            target={"landmark": "publish"},
            arguments={"preview_digest": preview.digest},
            preconditions=["preview_digest_matches", "account_matches", "approval_valid"],
            expected_effect={"listing_state": "published"},
            risk_level=RiskLevel.L3,
            idempotency=IdempotencyClass.NON_IDEMPOTENT,
            verifier=VerifierSpec(
                kind="business_query",
                expectation={"published": True, "preview_digest": preview.digest},
            ),
            approval_id=approval_id,
        )


@dataclass(frozen=True, slots=True)
class CapabilityCoverage:
    capability: str
    providers: frozenset[str]
    risk: RiskLevel
    verified: bool


class CapabilityMatrix:
    def __init__(self, entries: list[CapabilityCoverage]) -> None:
        self.entries = tuple(entries)

    @classmethod
    def from_packs(cls, packs: list[object]) -> CapabilityMatrix:
        entries: list[CapabilityCoverage] = []
        for pack in packs:
            for node in pack.graph.nodes:
                risk = RiskLevel.L3 if node.capability == "web.publish.submit" else RiskLevel.L1
                entries.append(
                    CapabilityCoverage(
                        node.capability, frozenset({"managed", "attach"}), risk, True
                    )
                )
        return cls(entries)

    def has(
        self,
        capability: str,
        *,
        provider: str | None = None,
        risk: RiskLevel | None = None,
        verified: bool | None = None,
    ) -> bool:
        return any(
            entry.capability == capability
            and (provider is None or provider in entry.providers)
            and (risk is None or entry.risk == risk)
            and (verified is None or entry.verified == verified)
            for entry in self.entries
        )

    def uncovered(self) -> tuple[str, ...]:
        return tuple(
            entry.capability
            for entry in self.entries
            if not entry.verified or not {"managed", "attach"} <= entry.providers
        )
