"""End-to-end comprehensive news report workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rich.console import Console

from ..ai.client import create_ai_client
from ..ai.tokens import get_usage_snapshot
from ..models import Config
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import StorageManager
from .analyzer import NewsDigestAnalyzer
from .renderer import NewsDigestRenderer
from .schemas import DailyNewsReport
from .selector import NewsMaterialSelector


class NewsDigestOrchestrator:
    def __init__(self, config: Config, storage: StorageManager, *, console: Console | None = None):
        self.config = config
        self.storage = storage
        self.settings = config.news_digest
        self.console = console or Console()

    async def run(self, *, force_hours: int | None = None) -> DailyNewsReport:
        if not self.settings.enabled:
            raise RuntimeError("news_digest.enabled is false")
        hours = force_hours or self.config.filtering.time_window_hours
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        self.console.print("[bold cyan]📰 News Digest - clustering multi-source events...[/bold cyan]\n")

        collector = HorizonOrchestrator(self.config, self.storage)
        fetched = await collector.fetch_all_sources(since)
        if collector.last_fetch_report and collector.last_fetch_report.all_failed:
            raise RuntimeError(collector.last_fetch_report.failure_message())
        deduped = collector.merge_cross_source_duplicates(fetched)
        selected = NewsMaterialSelector(self.settings).select(deduped)
        if not selected:
            raise RuntimeError("no eligible news materials were collected")
        self.console.print(
            f"📥 Fetched {len(fetched)} → {len(deduped)} URL-unique → "
            f"{len(selected)} source-balanced materials\n"
        )

        analyzer = NewsDigestAnalyzer(create_ai_client(self.config.ai), self.settings)
        draft = await analyzer.analyze(selected)
        events = analyzer.hydrate_events(draft, selected)
        if not events:
            raise RuntimeError(
                "AI returned no events that met the independent-source evidence policy"
            )
        publisher_keys = {analyzer.publisher_key(analyzer._publisher(item)) for item in selected}
        corroborated_count = sum(
            event.evidence_status == "corroborated" for event in events
        )
        primary_count = sum(event.evidence_status == "primary" for event in events)
        single_count = sum(
            event.evidence_status == "single_source" for event in events
        )
        overview = (
            f"今天归纳出 {len(events)} 个值得阅读的事件：{corroborated_count} 个得到多源印证，"
            f"{primary_count} 个来自官方或一手发布，{single_count} 个属于尚待交叉验证的单源观察。"
        )
        status_prefix = {
            "corroborated": "多源印证",
            "primary": "官方/一手",
            "single_source": "单源观察",
        }
        key_points = [
            f"【{status_prefix[event.evidence_status]}】{event.title}：{event.summary}"
            for event in events[:6]
        ]
        report = DailyNewsReport(
            report_date=datetime.now(timezone.utc).date(),
            fetched_count=len(fetched),
            deduped_count=len(deduped),
            selected_count=len(selected),
            publisher_count=len(publisher_keys),
            corroborated_event_count=corroborated_count,
            overview=overview,
            key_points=key_points,
            events=events,
            prompt_version=self.settings.prompt_version,
            model=self.config.ai.model,
        )
        markdown_path, json_path, post_path = NewsDigestRenderer().save(
            report,
            output_dir=self.settings.output_dir,
            docs_posts_dir=self.settings.docs_posts_dir,
        )
        self.console.print(f"💾 News report: {markdown_path}")
        self.console.print(f"🧾 Structured data: {json_path}")
        self.console.print(f"📄 GitHub Pages: {post_path}")
        usage = get_usage_snapshot()
        if usage.total_tokens:
            self.console.print(f"🧮 Token usage: {usage.total_tokens}")
        return report
