"""Static, interactive-friendly report rendering for GitHub Pages."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote, urlsplit

from .._file_utils import _atomic_write_text
from .schemas import DailyNewsReport, NewsEvent, NewsSource


def _text(value: object) -> str:
    return html.escape(" ".join(str(value).split()), quote=False)


def _attr(value: object) -> str:
    return html.escape(str(value), quote=True)


def _url(value: object) -> str | None:
    raw = str(value).strip()
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
    except ValueError:
        return None
    return html.escape(quote(raw, safe=":/?#[]@!$&'*,;=~%+"), quote=True)


class NewsDigestRenderer:
    TIER_LABELS = {
        "official": "官方/机构",
        "primary": "一手行业",
        "professional": "专业媒体",
        "community": "社区个例",
    }
    EVIDENCE_LABELS = {
        "corroborated": "多源印证",
        "primary": "官方/一手",
        "single_source": "单源观察",
    }

    def render(self, report: DailyNewsReport) -> str:
        lines = [
            f"# 今日综合新闻 - {report.report_date.isoformat()}",
            "",
            (
                '<div class="news-overview-data" '
                f'data-fetched="{report.fetched_count}" data-selected="{report.selected_count}" '
                f'data-publishers="{report.publisher_count}" data-events="{len(report.events)}" '
                f'data-corroborated="{report.corroborated_event_count}">'
            ),
            f'<p class="news-overview-text">{_text(report.overview)}</p>',
            '<ul class="news-key-points">',
        ]
        lines.extend(f"<li>{_text(point)}</li>" for point in report.key_points)
        lines.extend(["</ul>", "</div>", "", "## 今日事件", ""])
        if report.events:
            for index, event in enumerate(report.events, 1):
                lines.extend(self._render_event(index, event))
        else:
            lines.append("<p class=\"empty-state\">今天没有形成足够可信的多源事件。</p>")
        lines.extend(
            [
                "",
                "---",
                "",
                f"<small>Prompt: {_text(report.prompt_version)} · Model: {_text(report.model)}</small>",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_event(self, index: int, event: NewsEvent) -> list[str]:
        confidence = {"high": "高", "medium": "中", "low": "低"}[event.confidence]
        lines = [
            (
                f'<article class="news-event" id="event-{index}" '
                f'data-category="{_attr(event.category)}" data-evidence="{event.evidence_status}" '
                f'data-importance="{event.importance}">'
            ),
            '<header class="news-event__header">',
            f'<span class="news-event__category">{_text(event.category)}</span>',
            f'<span class="news-event__importance">重要度 {event.importance}</span>',
            f'<span class="news-event__evidence" data-status="{event.evidence_status}">'
            f'{self.EVIDENCE_LABELS[event.evidence_status]}</span>',
            f"<h3>{_text(event.title)}</h3>",
            "</header>",
            f'<p class="news-event__summary">{_text(event.summary)}</p>',
            '<div class="news-event__quick">',
            f'<div><strong>为什么重要</strong><p>{_text(event.why_it_matters)}</p></div>',
        ]
        if event.industry_impact:
            lines.append(f'<div><strong>行业影响</strong><p>{_text(event.industry_impact)}</p></div>')
        if event.individual_impact:
            lines.append(f'<div><strong>与你有关</strong><p>{_text(event.individual_impact)}</p></div>')
        lines.extend(["</div>", '<div class="news-event__actions">'])
        lines.extend(
            [
                '<details class="news-event__detail">',
                '<summary><span>查看完整分析</span><small>事实、宏观影响与后续观察</small></summary>',
                '<div class="news-event__detail-body">',
                "<h4>已确认事实</h4>",
                "<ul>",
            ]
        )
        lines.extend(f"<li>{_text(fact)}</li>" for fact in event.confirmed_facts)
        lines.extend(["</ul>"])
        if event.macro_impact:
            lines.extend(["<h4>宏观影响</h4>", f"<p>{_text(event.macro_impact)}</p>"])
        if event.different_views:
            lines.extend(["<h4>不同视角与局限</h4>", f"<p>{_text(event.different_views)}</p>"])
        if event.watch_next:
            lines.extend(["<h4>接下来观察</h4>", "<ul>"])
            lines.extend(f"<li>{_text(value)}</li>" for value in event.watch_next)
            lines.append("</ul>")
        lines.extend(["</div>", "</details>"])
        lines.extend(self._render_sources(event.sources, confidence))
        lines.extend(["</div>", "</article>", ""])
        return lines

    def _render_sources(self, sources: list[NewsSource], confidence: str) -> list[str]:
        publishers = len({source.publisher_key for source in sources})
        lines = [
            '<details class="news-event__sources">',
            (
                f"<summary><span>查看 {len(sources)} 个来源</span>"
                f"<small>{publishers} 个发布者 · 可信度 {confidence}</small></summary>"
            ),
            '<ol class="news-source-list">',
        ]
        for source in sources:
            safe_url = _url(source.url)
            title = _text(source.title)
            link = (
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{title}</a>'
                if safe_url
                else title
            )
            preferred = '<span class="news-source__preferred">偏好媒体</span>' if source.preferred else ""
            lines.extend(
                [
                    "<li>",
                    f'<div class="news-source__meta"><strong>{_text(source.publisher)}</strong>'
                    f'<span>{self.TIER_LABELS[source.source_tier]}</span>{preferred}</div>',
                    f"<p>{link}</p>",
                    f'<time datetime="{source.published_at.isoformat()}">{source.published_at:%Y-%m-%d %H:%M}</time>',
                    "</li>",
                ]
            )
        lines.extend(["</ol>", "</details>"])
        return lines

    def save(
        self,
        report: DailyNewsReport,
        *,
        output_dir: str | Path,
        docs_posts_dir: str | Path,
    ) -> tuple[Path, Path, Path]:
        output = Path(output_dir)
        posts = Path(docs_posts_dir)
        output.mkdir(parents=True, exist_ok=True)
        posts.mkdir(parents=True, exist_ok=True)
        date_text = report.report_date.isoformat()
        markdown_path = output / f"news-digest-{date_text}.md"
        json_path = output / f"news-digest-{date_text}.json"
        post_path = posts / f"{date_text}-news-digest.md"
        body = self.render(report)
        front_matter = (
            "---\nlayout: default\ncategory: news-digest\n"
            f'title: "今日综合新闻 - {date_text}"\ndate: {date_text}\n---\n\n'
        )
        _atomic_write_text(markdown_path, body)
        _atomic_write_text(json_path, report.model_dump_json(indent=2))
        _atomic_write_text(post_path, front_matter + body)
        return markdown_path, json_path, post_path
