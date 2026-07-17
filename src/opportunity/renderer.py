"""Programmatic Markdown rendering for Startup Radar reports."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from .._file_utils import _atomic_write_text
from ..storage.manager import safe_output_path
from .schemas import RadarReport, ScoredOpportunity


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#!|])")
_URL_SAFE_CHARS = ":/?#[]@!$&'*,;=~%+"


def _escape(value: object) -> str:
    text = " ".join(str(value).split())
    return _MARKDOWN_SPECIAL.sub(r"\\\1", html.escape(text, quote=False))


def _safe_url(value: object) -> str | None:
    raw = str(value).strip()
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
    except ValueError:
        return None
    return html.escape(quote(raw, safe=_URL_SAFE_CHARS), quote=True)


def _confidence(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value)


class StartupRadarRenderer:
    """Converts validated report JSON into one Chinese Markdown artifact."""

    def render(self, report: RadarReport) -> str:
        lines = [
            f"# 今日创业雷达 - {report.report_date.isoformat()}",
            "",
            (
                f"> 本次抓取 {report.fetched_count} 条材料，新增 {report.new_article_count} 条，"
                f"完成 {report.analyzed_count} 条创业信号分析。"
            ),
            "",
            self._render_funnel(report),
            "",
            self._render_source_counts(report.source_counts),
            "" if report.source_counts else "",
            "## 今天最值得关注",
            "",
        ]
        if report.signals:
            for signal in report.signals:
                trend = (
                    f"（近期开启 {signal.occurrence_count} 个独立证据，机会分 {signal.score:.1f}）"
                    if signal.occurrence_count > 1
                    else f"（机会分 {signal.score:.1f}）"
                )
                lines.extend(
                    [
                        f"- **{_escape(signal.signal)}** {trend}",
                        f"  {_escape(signal.why_now)}",
                    ]
                )
        else:
            lines.append("今天没有足够可信的新变化，宁缺毋滥。")

        lines.extend(["", "## 今日创业机会", ""])
        if report.opportunities:
            for index, opportunity in enumerate(report.opportunities, 1):
                lines.extend(self._render_opportunity(index, opportunity))
        else:
            lines.append("今天没有达到推荐阈值且未在近期重复输出的机会。")

        lines.extend(["", "## 今日不建议追", ""])
        if report.skipped:
            for item in report.skipped:
                source_url = _safe_url(item.source_url)
                source = (
                    f"[{_escape(item.source_title)}]({source_url})"
                    if source_url
                    else _escape(item.source_title)
                )
                lines.extend(
                    [
                        f"- **{_escape(item.signal)}**",
                        f"  原因：{_escape(item.reason)}",
                        f"  证据：{source}",
                    ]
                )
        else:
            lines.append("暂无需要明确排除的热点。")

        lines.extend(
            [
                "",
                "---",
                "",
                f"_Prompt: `{_escape(report.prompt_version)}` · Model: `{_escape(report.model)}`_",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _render_funnel(report: RadarReport) -> str:
        if not report.prefiltered_count:
            return ""
        return (
            f"> 选材漏斗：URL 去重后 {report.deduped_count} 条 → "
            f"本地零 Token 预筛 {report.prefiltered_count} 条 → "
            f"AI 轻量初筛 {report.triaged_count} 条 → "
            f"深度分析 {report.analyzed_count} 条"
        )

    @staticmethod
    def _render_source_counts(counts: dict[str, int]) -> str:
        if not counts:
            return ""
        labels = {
            "reddit": "Reddit 用户痛点",
            "rss": "多领域 RSS",
            "google_news": "Google News 商业/消费",
            "hackernews": "Hacker News",
            "developer": "GitHub/OSS Insight",
        }
        values = [f"{labels.get(key, key)} {value}" for key, value in counts.items()]
        return "> 送入分析的来源：" + " · ".join(values)

    def _render_opportunity(self, index: int, item: ScoredOpportunity) -> list[str]:
        analysis = item.candidate.analysis
        url = _safe_url(item.candidate.source_url)
        source = (
            f"[{_escape(item.candidate.source_title)}]({url})"
            if url
            else _escape(item.candidate.source_title)
        )
        risks = "；".join(_escape(risk) for risk in analysis.risks) or "暂无明确风险信息"
        evidence = "；".join(_escape(value) for value in analysis.evidence)
        trend = (
            f"累计 {item.occurrence_count} 次信号 / {item.source_count} 类来源"
            if item.occurrence_count > 1
            else "首次出现"
        )
        return [
            f"### {index}. {_escape(analysis.signal)} — {item.total_score:.1f}/100",
            "",
            f"- **目标用户：** {_escape(analysis.target_user)}",
            f"- **当前痛点：** {_escape(analysis.pain_point)}",
            f"- **现有方案：** {_escape(analysis.current_solution)}",
            f"- **为什么是现在：** {_escape(analysis.why_now)}",
            f"- **商业模式：** {_escape(analysis.business_model)}",
            f"- **为什么适合独立开发：** {_escape(analysis.indie_advantage)}",
            (
                f"- **为什么适合我：** {_escape(analysis.personal_fit_reason)}"
                f"（匹配度 {analysis.personal_fit:.1f}/10）"
            ),
            f"- **7 天 MVP：** {_escape(analysis.seven_day_mvp)}",
            f"- **第一批用户在哪里：** {_escape(analysis.first_users)}",
            f"- **风险：** {risks}",
            f"- **信心等级：** {_confidence(analysis.confidence)}（{trend}）",
            f"- **证据：** {evidence}",
            f"- **原始材料：** {source}",
            "",
        ]

    def save(
        self,
        report: RadarReport,
        *,
        output_dir: str | Path,
        docs_posts_dir: str | Path,
    ) -> tuple[Path, Path]:
        markdown = self.render(report)
        filename = f"startup-radar-{report.report_date.isoformat()}.md"
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = safe_output_path(output_root, filename)
        _atomic_write_text(output_path, markdown)

        docs_root = Path(docs_posts_dir)
        docs_root.mkdir(parents=True, exist_ok=True)
        post_path = safe_output_path(
            docs_root, f"{report.report_date.isoformat()}-startup-radar.md"
        )
        front_matter = (
            "---\n"
            "layout: default\n"
            f'title: "今日创业雷达：{report.report_date.isoformat()}"\n'
            f"date: {report.report_date.isoformat()}\n"
            "lang: zh\n"
            "category: startup-radar\n"
            "---\n\n"
        )
        body = markdown.split("\n", 1)[1].lstrip() if "\n" in markdown else markdown
        _atomic_write_text(post_path, front_matter + body)
        return output_path, post_path
