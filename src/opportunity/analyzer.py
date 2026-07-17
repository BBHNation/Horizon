"""AI-backed startup opportunity analysis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pydantic import ValidationError
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from ..models import ContentItem
from .prompts import (
    OPPORTUNITY_ANALYSIS_SYSTEM,
    OPPORTUNITY_DEDUP_SYSTEM,
    build_analysis_prompt,
    build_dedup_prompt,
)
from .schemas import (
    DirectionResolution,
    OpportunityAnalysis,
    OpportunityCandidate,
    StartupProfile,
)


@dataclass
class AnalysisBatchResult:
    candidates: list[OpportunityCandidate] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class OpportunityAnalyzer:
    """Turns source material into validated JSON opportunity candidates."""

    def __init__(self, ai_client: AIClient, profile: StartupProfile, console: Console | None = None):
        self.ai_client = ai_client
        self.profile = profile
        self.console = console or Console()

    def _concurrency(self) -> int:
        config = getattr(self.ai_client, "config", None)
        return max(1, int(getattr(config, "analysis_concurrency", 1)))

    @staticmethod
    def _engagement(item: ContentItem) -> str:
        keys = (
            "score",
            "descendants",
            "favorite_count",
            "retweet_count",
            "reply_count",
            "views",
            "stars",
        )
        parts = [f"{key}={item.metadata[key]}" for key in keys if item.metadata.get(key) is not None]
        return ", ".join(parts)

    async def analyze_batch(
        self,
        articles: list[tuple[ContentItem, str]],
    ) -> AnalysisBatchResult:
        result = AnalysisBatchResult()
        semaphore = asyncio.Semaphore(self._concurrency())

        async def process(item: ContentItem, article_hash: str, task_id: object) -> None:
            async with semaphore:
                try:
                    candidate = await self.analyze_one(item, article_hash)
                    result.candidates.append(candidate)
                except Exception as exc:
                    result.failures.append(f"{item.id}: {type(exc).__name__}: {exc}")
                finally:
                    progress.advance(task_id)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task_id = progress.add_task("Analyzing startup signals", total=len(articles))
            await asyncio.gather(
                *(process(item, article_hash, task_id) for item, article_hash in articles)
            )
        return result

    async def analyze_one(self, item: ContentItem, article_hash: str) -> OpportunityCandidate:
        prompt = build_analysis_prompt(
            profile=self.profile,
            title=item.title,
            source=item.source_type.value,
            author=item.author or "unknown",
            published_at=item.published_at.isoformat(),
            url=str(item.url),
            engagement=self._engagement(item),
            content=(item.content or "")[:6000],
        )

        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await self.ai_client.complete(
                    system=OPPORTUNITY_ANALYSIS_SYSTEM,
                    user=prompt,
                    temperature=0.1,
                )
                payload = parse_json_response(response)
                if payload is None:
                    raise ValueError("AI response did not contain a JSON object")
                analysis = OpportunityAnalysis.model_validate(payload)
                analysis.score_dimensions.personal_match = analysis.personal_fit
                if not analysis.evidence:
                    analysis.evidence = [f"{item.title} — {item.url}"]
                return OpportunityCandidate(
                    analysis=analysis,
                    article_hash=article_hash,
                    source_title=item.title,
                    source_url=str(item.url),
                    source_type=item.source_type.value,
                    published_at=item.published_at,
                )
            except (ValidationError, ValueError) as exc:
                last_error = exc
                prompt += (
                    "\n\n上一次响应未通过 Schema 或语言校验。请重新输出完整 JSON，"
                    "确保除 direction_key 外的所有叙述字段均为简体中文。"
                )
        raise ValueError(f"invalid structured opportunity response: {last_error}")

    async def resolve_direction_aliases(
        self,
        candidates: list[OpportunityCandidate],
        historical_directions: list[dict[str, str]],
    ) -> None:
        """Map semantically identical current and historical directions to one key."""
        if not candidates:
            return
        candidate_payload = [
            {
                "candidate_index": index,
                "direction_key": item.analysis.direction_key,
                "signal": item.analysis.signal,
                "target_user": item.analysis.target_user,
                "pain_point": item.analysis.pain_point,
                "seven_day_mvp": item.analysis.seven_day_mvp,
            }
            for index, item in enumerate(candidates)
        ]
        try:
            response = await self.ai_client.complete(
                system=OPPORTUNITY_DEDUP_SYSTEM,
                user=build_dedup_prompt(candidate_payload, historical_directions),
                temperature=0,
            )
            payload = parse_json_response(response)
            resolution = DirectionResolution.model_validate(payload)
        except Exception:
            return

        allowed_keys = {
            item.analysis.direction_key for item in candidates
        } | {item["direction_key"] for item in historical_directions}
        for mapping in resolution.mappings:
            if mapping.candidate_index >= len(candidates):
                continue
            if mapping.canonical_key not in allowed_keys:
                continue
            candidates[mapping.candidate_index].analysis.direction_key = mapping.canonical_key
