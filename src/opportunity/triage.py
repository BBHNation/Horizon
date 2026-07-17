"""Token-efficient batch triage before full opportunity analysis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.console import Console

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from ..models import ContentItem
from .prompts import OPPORTUNITY_TRIAGE_SYSTEM, build_triage_prompt
from .schemas import StartupProfile, TriageDecision, TriageResponse


@dataclass
class TriageBatchResult:
    decisions: dict[str, TriageDecision] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


class OpportunityTriage:
    """Scores compact material cards in batches to minimize repeated prompts."""

    def __init__(
        self,
        ai_client: AIClient,
        profile: StartupProfile,
        *,
        batch_size: int = 15,
        excerpt_chars: int = 320,
        max_tokens: int = 2500,
        concurrency: int = 2,
        console: Console | None = None,
    ):
        self.ai_client = ai_client
        self.profile = profile
        self.batch_size = batch_size
        self.excerpt_chars = excerpt_chars
        self.max_tokens = max_tokens
        self.concurrency = concurrency
        self.console = console or Console()

    async def score(
        self, articles: list[tuple[ContentItem, str]]
    ) -> TriageBatchResult:
        result = TriageBatchResult()
        batches = [
            articles[index : index + self.batch_size]
            for index in range(0, len(articles), self.batch_size)
        ]
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(batch_number: int, batch: list[tuple[ContentItem, str]]) -> None:
            async with semaphore:
                try:
                    decisions = await self._score_batch(batch)
                    result.decisions.update(decisions)
                except Exception as exc:
                    result.failures.append(
                        f"triage batch {batch_number}: {type(exc).__name__}: {exc}"
                    )

        await asyncio.gather(
            *(process(index + 1, batch) for index, batch in enumerate(batches))
        )
        return result

    async def _score_batch(
        self, batch: list[tuple[ContentItem, str]]
    ) -> dict[str, TriageDecision]:
        cards = [self._card(item, article_hash) for item, article_hash in batch]
        prompt = build_triage_prompt(profile=self.profile, articles=cards)
        expected = {article_hash for _, article_hash in batch}
        last_error: Exception | None = None

        for _ in range(2):
            try:
                response = await self.ai_client.complete(
                    system=OPPORTUNITY_TRIAGE_SYSTEM,
                    user=prompt,
                    temperature=0,
                    max_tokens=self.max_tokens,
                )
                payload = parse_json_response(response)
                if payload is None:
                    raise ValueError("triage response did not contain JSON")
                parsed = TriageResponse.model_validate(payload)
                decisions = {
                    decision.article_id: decision
                    for decision in parsed.items
                    if decision.article_id in expected
                }
                missing = expected - set(decisions)
                if missing:
                    raise ValueError(f"triage response omitted {len(missing)} article(s)")
                return decisions
            except Exception as exc:
                last_error = exc
                prompt += (
                    "\n上一次响应无效。请严格返回输入中的每个 article_id，"
                    "不要省略或改写 ID。"
                )
        raise ValueError(f"invalid triage response: {last_error}")

    def _card(self, item: ContentItem, article_hash: str) -> dict[str, object]:
        content = " ".join((item.content or "").split())[: self.excerpt_chars]
        metadata_keys = (
            "score",
            "num_comments",
            "descendants",
            "stars_gained",
            "feed_name",
            "subreddit",
            "source_name",
            "category",
        )
        metadata = {
            key: item.metadata[key]
            for key in metadata_keys
            if item.metadata.get(key) is not None
        }
        return {
            "article_id": article_hash,
            "title": item.title[:240],
            "source": item.source_type.value,
            "published_at": item.published_at.isoformat(),
            "metadata": metadata,
            "excerpt": content or "无摘要，请仅根据标题谨慎评分。",
        }
