"""Persist the complete fetched-source inventory for coverage review."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .._file_utils import _atomic_write_text
from ..models import ContentItem, SourceType


_GROUP_LABELS = {
    "reddit": "Reddit 用户痛点",
    "rss": "多领域 RSS",
    "google_news": "Google News 商业/消费",
    "hackernews": "Hacker News",
    "developer": "GitHub/OSS Insight",
    "other": "其他",
}


def source_group(item: ContentItem) -> str:
    if item.source_type == SourceType.REDDIT:
        return "reddit"
    if item.source_type == SourceType.GOOGLE_NEWS:
        return "google_news"
    if item.source_type == SourceType.HACKERNEWS:
        return "hackernews"
    if item.source_type in {SourceType.GITHUB, SourceType.OSSINSIGHT}:
        return "developer"
    if item.source_type == SourceType.RSS:
        return (
            "developer"
            if item.metadata.get("category") == "github-trending"
            else "rss"
        )
    return "other"


def specific_source(item: ContentItem) -> str:
    """Return the most useful human-facing source/community/publisher label."""
    if item.source_type == SourceType.REDDIT:
        subreddit = item.metadata.get("subreddit")
        if subreddit:
            return f"r/{subreddit}"
        domain = urlsplit(str(item.url)).hostname
        return f"Reddit · {domain}" if domain else "Reddit"
    if item.source_type == SourceType.RSS:
        return str(item.metadata.get("feed_name") or "RSS")
    if item.source_type == SourceType.GOOGLE_NEWS:
        return str(item.metadata.get("source_name") or "Google News")
    if item.source_type == SourceType.HACKERNEWS:
        domain = urlsplit(str(item.url)).hostname
        return f"Hacker News · {domain}" if domain else "Hacker News"
    if item.source_type in {SourceType.GITHUB, SourceType.OSSINSIGHT}:
        return str(item.metadata.get("repo") or item.author or item.source_type.value)
    return item.source_type.value


class SourceInventoryWriter:
    """Writes all URL-unique fetched materials as JSON and Markdown."""

    def save(
        self,
        items: list[ContentItem],
        *,
        report_date: date,
        output_dir: str | Path,
    ) -> tuple[Path, Path]:
        rows = [self._row(item) for item in items]
        rows.sort(
            key=lambda row: (
                row["source_group"],
                row["source"].lower(),
                row["published_at"],
            ),
            reverse=True,
        )
        group_counts = Counter(row["source_group"] for row in rows)
        source_counts = Counter(row["source"] for row in rows)

        root = Path(output_dir) / "sources"
        root.mkdir(parents=True, exist_ok=True)
        stem = f"source-inventory-{report_date.isoformat()}"
        json_path = root / f"{stem}.json"
        markdown_path = root / f"{stem}.md"

        payload = {
            "report_date": report_date.isoformat(),
            "total": len(rows),
            "group_counts": dict(sorted(group_counts.items())),
            "source_counts": dict(sorted(source_counts.items())),
            "items": rows,
        }
        _atomic_write_text(
            json_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        _atomic_write_text(
            markdown_path,
            self._render_markdown(report_date, rows, group_counts, source_counts),
        )
        return json_path, markdown_path

    @staticmethod
    def _row(item: ContentItem) -> dict[str, object]:
        return {
            "source_group": source_group(item),
            "source_type": item.source_type.value,
            "source": specific_source(item),
            "category": item.metadata.get("category"),
            "configured_topic": item.metadata.get("gn_query"),
            "title": item.title,
            "url": str(item.url),
            "published_at": item.published_at.isoformat(),
        }

    def _render_markdown(
        self,
        report_date: date,
        rows: list[dict[str, object]],
        group_counts: Counter,
        source_counts: Counter,
    ) -> str:
        lines = [
            f"# 信息源清单 - {report_date.isoformat()}",
            "",
            f"> 共保留 {len(rows)} 条 URL 去重后的抓取结果。这里展示的是全部来源，不是仅进入 AI 分析的材料。",
            "",
            "## 来源数量概览",
            "",
            "| 来源 | 条数 | 占比 |",
            "|---|---:|---:|",
        ]
        for source, count in source_counts.most_common():
            ratio = count / len(rows) * 100 if rows else 0
            lines.append(f"| {self._escape(source)} | {count} | {ratio:.1f}% |")
        lines.append("")
        for group in _GROUP_LABELS:
            group_rows = [row for row in rows if row["source_group"] == group]
            if not group_rows:
                continue
            lines.extend(
                [
                    f"## {_GROUP_LABELS[group]}（{group_counts[group]}）",
                    "",
                    "| 来源 | 标题 | 链接 | 分类 |",
                    "|---|---|---|---|",
                ]
            )
            for row in group_rows:
                lines.append(
                    "| {source} | {title} | [查看原文]({url}) | {category} |".format(
                        source=self._escape(row["source"]),
                        title=self._escape(row["title"]),
                        url=str(row["url"]).replace(")", "%29"),
                        category=self._escape(row["category"] or "—"),
                    )
                )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _escape(value: object) -> str:
        return " ".join(str(value).split()).replace("|", "\\|")
