"""Typed contracts for Startup Radar AI output and rendered reports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Confidence = Literal["low", "medium", "high"]
Recommendation = Literal["pursue", "watch", "skip"]


class StartupProfile(BaseModel):
    """The builder profile used to personalize opportunity analysis."""

    technical_strengths: list[str] = Field(default_factory=list)
    interested_domains: list[str] = Field(default_factory=list)
    constraints: dict[str, object] = Field(default_factory=dict)


class ScoreDimensions(BaseModel):
    """Raw 0-10 judgments used by the deterministic scoring layer."""

    pain_intensity: float = Field(ge=0, le=10)
    user_scale: float = Field(ge=0, le=10)
    occurrence_frequency: float = Field(ge=0, le=10)
    solution_maturity: float = Field(ge=0, le=10)
    why_now_strength: float = Field(ge=0, le=10)
    ai_cost_leverage: float = Field(ge=0, le=10)
    indie_suitability: float = Field(ge=0, le=10)
    personal_match: float = Field(ge=0, le=10)
    mvp_difficulty: float = Field(ge=0, le=10)
    evidence_credibility: float = Field(ge=0, le=10)


class OpportunityAnalysis(BaseModel):
    """Strict JSON shape returned by the AI for one source article."""

    signal: str = Field(min_length=1)
    direction_key: str = Field(
        min_length=1,
        description="Stable lowercase English key for semantically identical startup directions",
    )
    target_user: str = Field(min_length=1)
    pain_point: str = Field(min_length=1)
    current_solution: str = Field(min_length=1)
    why_now: str = Field(min_length=1)
    business_model: str = Field(min_length=1)
    indie_advantage: str = Field(min_length=1)
    personal_fit: float = Field(ge=0, le=10)
    personal_fit_reason: str = Field(min_length=1)
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)
    seven_day_mvp: str = Field(min_length=1)
    first_users: str = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    recommendation: Recommendation
    not_recommended_reason: str = ""
    score_dimensions: ScoreDimensions

    @field_validator("direction_key")
    @classmethod
    def normalize_direction_key(cls, value: str) -> str:
        normalized = "-".join(value.strip().lower().replace("_", "-").split())
        return normalized[:120]

    @model_validator(mode="after")
    def require_chinese_narrative(self) -> "OpportunityAnalysis":
        narrative_fields = (
            "signal",
            "target_user",
            "pain_point",
            "current_solution",
            "why_now",
            "business_model",
            "indie_advantage",
            "personal_fit_reason",
            "seven_day_mvp",
            "first_users",
        )
        for field_name in narrative_fields:
            value = getattr(self, field_name)
            if value and not any("\u3400" <= char <= "\u9fff" for char in value):
                raise ValueError(f"{field_name} must contain Simplified Chinese narrative")
        return self


class OpportunityCandidate(BaseModel):
    """AI analysis combined with trusted source metadata."""

    analysis: OpportunityAnalysis
    article_hash: str
    source_title: str
    source_url: str
    source_type: str
    published_at: datetime


class DirectionMapping(BaseModel):
    candidate_index: int = Field(ge=0)
    canonical_key: str = Field(min_length=1)

    @field_validator("canonical_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return "-".join(value.strip().lower().replace("_", "-").split())[:120]


class DirectionResolution(BaseModel):
    mappings: list[DirectionMapping] = Field(default_factory=list)


class ScoredOpportunity(BaseModel):
    """A candidate after deterministic and historical scoring."""

    candidate: OpportunityCandidate
    total_score: float = Field(ge=0, le=100)
    base_score: float = Field(ge=0, le=100)
    history_boost: float = Field(ge=0, le=10)
    occurrence_count: int = Field(ge=1)
    source_count: int = Field(ge=1)
    first_seen: datetime
    last_seen: datetime
    recently_output: bool = False


class RadarSignal(BaseModel):
    signal: str
    why_now: str
    direction_key: str
    score: float
    occurrence_count: int = 1


class SkippedTrend(BaseModel):
    signal: str
    reason: str
    source_title: str
    source_url: str


class RadarReport(BaseModel):
    """Renderer input; no Markdown is produced by the AI."""

    report_date: date
    fetched_count: int
    new_article_count: int
    analyzed_count: int
    signals: list[RadarSignal] = Field(default_factory=list)
    opportunities: list[ScoredOpportunity] = Field(default_factory=list)
    skipped: list[SkippedTrend] = Field(default_factory=list)
    prompt_version: str
    model: str
