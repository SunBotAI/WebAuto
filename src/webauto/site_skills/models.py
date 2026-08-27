"""Strict declarative Site Skill schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageDefinition(SkillModel):
    url_patterns: list[str] = Field(default_factory=list)
    dom_markers: list[str] = Field(default_factory=list)
    a11y_markers: list[str] = Field(default_factory=list)
    visual_signatures: list[str] = Field(default_factory=list)


class LandmarkDefinition(SkillModel):
    selector: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list)


class ActionTemplate(SkillModel):
    kind: str = Field(min_length=1)
    target: dict[str, Any]
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillVerifier(SkillModel):
    kind: str
    expectation: dict[str, Any]


class CapabilityTemplate(SkillModel):
    page: str
    preconditions: list[str] = Field(min_length=1)
    actions: list[ActionTemplate] = Field(min_length=1)
    verifier: SkillVerifier
    recovery: list[str] = Field(min_length=1)


class SkillManifest(SkillModel):
    schema_version: str = "1.0"
    site: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    pages: dict[str, PageDefinition] = Field(min_length=1)
    capabilities: dict[str, CapabilityTemplate] = Field(min_length=1)
    landmarks: dict[str, LandmarkDefinition] = Field(default_factory=dict)
    fixtures: list[str] = Field(min_length=1)
