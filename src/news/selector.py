"""Deterministic source-balanced selection before AI synthesis."""

from __future__ import annotations

from collections import defaultdict

from ..models import ContentItem, NewsDigestConfig
from .analyzer import NewsDigestAnalyzer


class NewsMaterialSelector:
    def __init__(self, settings: NewsDigestConfig):
        self.settings = settings

    @staticmethod
    def _category(item: ContentItem) -> str:
        raw = str(item.metadata.get("category") or "")
        mapping = {
            "macro": "宏观经济",
            "econom": "宏观经济",
            "policy": "政策监管",
            "regulat": "政策监管",
            "industry": "产业公司",
            "business": "产业公司",
            "company": "产业公司",
            "tech": "科技产品",
            "ai-": "科技产品",
            "github": "科技产品",
            "consumer": "消费社会",
            "social": "消费社会",
            "education": "消费社会",
            "travel": "消费社会",
        }
        folded = raw.casefold()
        for token, category in mapping.items():
            if token in folded:
                return category
        return "产业公司"

    def _preferred(self, item: ContentItem) -> bool:
        if item.metadata.get("preferred"):
            return True
        publisher = NewsDigestAnalyzer._publisher(item).casefold()
        return any(name.casefold() in publisher for name in self.settings.preferred_publishers)

    def _rank(self, item: ContentItem) -> tuple[int, int, float]:
        tier = NewsDigestAnalyzer._tier(item)
        tier_score = {"official": 4, "primary": 3, "professional": 2, "community": 0}[tier]
        return tier_score, int(self._preferred(item)), item.published_at.timestamp()

    def select(self, items: list[ContentItem]) -> list[ContentItem]:
        publisher_counts: dict[str, int] = defaultdict(int)
        category_pools: dict[str, list[ContentItem]] = {
            category: [] for category in self.settings.categories
        }
        community_limit = int(self.settings.max_input_items * self.settings.community_max_ratio)
        community_count = 0

        for item in sorted(items, key=self._rank, reverse=True):
            publisher = NewsDigestAnalyzer._publisher(item).casefold()
            if publisher_counts[publisher] >= self.settings.max_items_per_publisher:
                continue
            if NewsDigestAnalyzer._tier(item) == "community":
                if community_count >= community_limit:
                    continue
                community_count += 1
            publisher_counts[publisher] += 1
            category_pools[self._category(item)].append(item)

        selected: list[ContentItem] = []
        while len(selected) < self.settings.max_input_items:
            added = False
            for category in self.settings.categories:
                pool = category_pools[category]
                if pool and len(selected) < self.settings.max_input_items:
                    selected.append(pool.pop(0))
                    added = True
            if not added:
                break
        return selected
