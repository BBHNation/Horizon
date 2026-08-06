"""Validated data contracts for the comprehensive news digest."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


NewsCategory = Literal["宏观经济", "政策监管", "产业公司", "科技产品", "消费社会"]
Confidence = Literal["high", "medium", "low"]


class NewsSource(BaseModel):
    source_id: int = Field(gt=0)
    publisher: str = Field(min_length=1)
    publisher_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    published_at: datetime
    source_tier: Literal["official", "primary", "professional", "community"]
    preferred: bool = False


class NewsEventDraft(BaseModel):
    title: str = Field(min_length=1)
    category: NewsCategory
    importance: int = Field(ge=1, le=100)
    confidence: Confidence
    summary: str = Field(min_length=1)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=6)
    why_it_matters: str = Field(min_length=1)
    macro_impact: str = ""
    industry_impact: str = ""
    individual_impact: str = ""
    different_views: str = ""
    watch_next: list[str] = Field(default_factory=list, max_length=5)
    source_ids: list[int] = Field(min_length=1, max_length=10)


class NewsDigestDraft(BaseModel):
    overview: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1, max_length=6)
    events: list[NewsEventDraft] = Field(default_factory=list)


class NewsEvent(BaseModel):
    title: str
    category: NewsCategory
    importance: int
    confidence: Confidence
    evidence_status: Literal["corroborated", "primary", "single_source"]
    summary: str
    confirmed_facts: list[str]
    why_it_matters: str
    macro_impact: str = ""
    industry_impact: str = ""
    individual_impact: str = ""
    different_views: str = ""
    watch_next: list[str]
    sources: list[NewsSource]


class DailyNewsReport(BaseModel):
    report_date: date
    fetched_count: int = Field(ge=0)
    deduped_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    publisher_count: int = Field(ge=0)
    corroborated_event_count: int = Field(ge=0)
    overview: str
    key_points: list[str]
    events: list[NewsEvent]
    prompt_version: str
    model: str
