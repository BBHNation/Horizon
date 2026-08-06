"""AI-backed multi-source event clustering and synthesis."""

from __future__ import annotations

from pydantic import ValidationError

from ..ai.utils import parse_json_response
from ..models import ContentItem, NewsDigestConfig
from .prompts import NEWS_DIGEST_SYSTEM, build_news_digest_prompt
from .schemas import DailyNewsReport, NewsDigestDraft, NewsEvent, NewsSource


class NewsDigestAnalyzer:
    def __init__(self, ai_client, settings: NewsDigestConfig):
        self.ai_client = ai_client
        self.settings = settings

    @staticmethod
    def _publisher(item: ContentItem) -> str:
        return str(
            item.metadata.get("source_name")
            or item.metadata.get("feed_name")
            or item.author
            or item.source_type.value
        )

    @staticmethod
    def _tier(item: ContentItem) -> str:
        configured = item.metadata.get("source_tier")
        if configured in {"official", "primary", "professional", "community"}:
            return str(configured)
        if item.source_type.value in {"reddit", "hackernews", "telegram", "twitter"}:
            return "community"
        if item.source_type.value in {"github", "ossinsight", "openbb"}:
            return "primary"
        return "professional"

    @staticmethod
    def publisher_key(publisher: str) -> str:
        folded = publisher.casefold()
        aliases = {
            "bbc": ("bbc",),
            "cnn": ("cnn",),
            "xinhua": ("新华社", "新华网", "xinhua"),
            "zaobao": ("联合早报", "zaobao"),
            "asahi": ("朝日新闻", "朝日新聞", "asahi"),
            "thepaper": ("澎湃", "the paper"),
            "36kr": ("36氪", "36kr"),
        }
        for key, names in aliases.items():
            if any(name in folded for name in names):
                return key
        return folded.strip()

    async def analyze(
        self, items: list[ContentItem], *, retry_feedback: str = ""
    ) -> NewsDigestDraft:
        prompt = build_news_digest_prompt(
            items,
            categories=self.settings.categories,
            max_events=self.settings.max_events,
            excerpt_chars=self.settings.excerpt_chars,
        )
        if retry_feedback:
            prompt += f"\n\n额外修正要求：{retry_feedback}"
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await self.ai_client.complete(
                    system=NEWS_DIGEST_SYSTEM,
                    user=prompt,
                    temperature=0.1,
                    max_tokens=self.settings.max_output_tokens,
                )
                payload = parse_json_response(response)
                if payload is None:
                    raise ValueError("AI response did not contain a JSON object")
                return NewsDigestDraft.model_validate(payload)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                prompt += "\n上一次输出未通过校验。请严格按指定 JSON Schema 完整重写。"
        raise ValueError(f"invalid structured news digest response: {last_error}")

    def hydrate_events(
        self, draft: NewsDigestDraft, items: list[ContentItem]
    ) -> list[NewsEvent]:
        source_map = {
            index: NewsSource(
                source_id=index,
                publisher=self._publisher(item),
                publisher_key=self.publisher_key(self._publisher(item)),
                title=item.title,
                url=str(item.url),
                published_at=item.published_at,
                source_tier=self._tier(item),
                preferred=bool(item.metadata.get("preferred")),
            )
            for index, item in enumerate(items, 1)
        }
        events = []
        for event in draft.events[: self.settings.max_events]:
            sources = []
            seen = set()
            for source_id in event.source_ids:
                if source_id in source_map and source_id not in seen:
                    sources.append(source_map[source_id])
                    seen.add(source_id)
            if not sources:
                continue
            publisher_count = len({source.publisher_key for source in sources})
            tiers = {source.source_tier for source in sources}
            if publisher_count < 2 and tiers == {"community"}:
                continue
            payload = event.model_dump(exclude={"source_ids"})
            if publisher_count >= 2 and ("official" in tiers or publisher_count >= 3):
                payload["confidence"] = "high"
                payload["evidence_status"] = "corroborated"
            elif publisher_count >= 2 or tiers.intersection({"official", "primary"}):
                payload["confidence"] = "medium"
                payload["evidence_status"] = (
                    "corroborated" if publisher_count >= 2 else "primary"
                )
            else:
                payload["confidence"] = "low"
                payload["evidence_status"] = "single_source"
            events.append(NewsEvent(**payload, sources=sources))
        order = {"corroborated": 2, "primary": 1, "single_source": 0}
        return sorted(
            events,
            key=lambda event: (order[event.evidence_status], event.importance),
            reverse=True,
        )
