"""End-to-end Startup Radar workflow built on Horizon's collection layer."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml
from rich.console import Console

from ..ai.client import create_ai_client
from ..ai.tokens import get_usage_snapshot
from ..extractors.trafilatura import TrafilaturaExtractor
from ..models import Config, ContentItem, TrafilaturaExtractorConfig
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import StorageManager
from .analyzer import OpportunityAnalyzer
from .history import HistoryStore
from .prompts import PROMPT_VERSION
from .renderer import StartupRadarRenderer
from .schemas import RadarReport, RadarSignal, ScoredOpportunity, SkippedTrend, StartupProfile
from .scorer import OpportunityScorer


class StartupRadarOrchestrator:
    """Coordinates collection, structured AI analysis, history, scoring, and output."""

    def __init__(
        self,
        config: Config,
        storage: StorageManager,
        *,
        profile_path: str | Path | None = None,
        console: Console | None = None,
    ):
        self.config = config
        self.storage = storage
        self.settings = config.startup_radar
        self.profile_path = Path(profile_path or self.settings.profile_path)
        self.console = console or Console()

    def load_profile(self) -> StartupProfile:
        if not self.profile_path.exists():
            raise FileNotFoundError(
                f"Startup profile not found: {self.profile_path}. Create it from profile.yml."
            )
        with self.profile_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return StartupProfile.model_validate(payload)

    @staticmethod
    def _article_priority(item: ContentItem) -> tuple[float, float, float]:
        engagement = float(item.metadata.get("score") or item.metadata.get("stars") or 0)
        content_size = min(len(item.content or ""), 5000) / 5000
        published = item.published_at.timestamp()
        return engagement, content_size, published

    async def run(
        self, *, force_hours: int | None = None, reanalyze: bool = False
    ) -> RadarReport | None:
        if not self.settings.enabled:
            raise RuntimeError("startup_radar.enabled is false")

        profile = self.load_profile()
        report_date = datetime.now(timezone.utc).date()
        hours = force_hours or self.config.filtering.time_window_hours
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        self.console.print("[bold cyan]🚀 Startup Radar - discovering opportunities...[/bold cyan]\n")
        collector = HorizonOrchestrator(self.config, self.storage)
        fetched = await collector.fetch_all_sources(since)
        if collector.last_fetch_report and collector.last_fetch_report.all_failed:
            raise RuntimeError(collector.last_fetch_report.failure_message())
        deduped = collector.merge_cross_source_duplicates(fetched)
        extracted_count = await self._ensure_article_bodies(deduped)
        self.console.print(f"📥 Fetched {len(fetched)} items → {len(deduped)} URL-unique materials\n")
        if extracted_count:
            self.console.print(f"📄 Extracted full text for {extracted_count} short materials\n")

        ai_client = create_ai_client(self.config.ai)
        analyzer = OpportunityAnalyzer(ai_client, profile, self.console)
        scorer = OpportunityScorer()
        renderer = StartupRadarRenderer()

        with HistoryStore(self.settings.database_path) as history:
            prompt_version = self.settings.prompt_version or PROMPT_VERSION
            queued: list[tuple[ContentItem, str]] = []
            new_article_count = 0
            for item in deduped:
                article_hash, is_new = history.add_article(item)
                new_article_count += int(is_new)
                if reanalyze or not history.was_analyzed(article_hash, prompt_version):
                    queued.append((item, article_hash))

            queued.sort(key=lambda pair: self._article_priority(pair[0]), reverse=True)
            queued = queued[: self.settings.max_articles_per_run]
            current_output = (
                Path(self.settings.output_dir)
                / f"startup-radar-{report_date.isoformat()}.md"
            )
            if not queued and current_output.exists() and not reanalyze:
                self.console.print(
                    f"✅ No new materials; keeping existing radar unchanged: {current_output}"
                )
                return None
            self.console.print(
                f"🧠 {len(queued)} materials require structured opportunity analysis\n"
            )
            batch = await analyzer.analyze_batch(queued)
            for failure in batch.failures[:5]:
                self.console.print(f"[yellow]⚠️  {failure}[/yellow]")
            if len(batch.failures) > 5:
                self.console.print(f"[yellow]⚠️  and {len(batch.failures) - 5} more failures[/yellow]")

            await analyzer.resolve_direction_aliases(
                batch.candidates,
                history.list_directions(),
            )

            preliminaries: list[tuple[object, float]] = []
            for candidate in batch.candidates:
                base_score = scorer.base_score(candidate)
                history.record_candidate(
                    candidate,
                    score=base_score,
                    prompt_version=prompt_version,
                    model=self.config.ai.model,
                    run_date=report_date,
                )
                preliminaries.append((candidate, base_score))

            scored: list[ScoredOpportunity] = []
            for candidate, _ in preliminaries:
                stats = history.event_stats(candidate.analysis.direction_key)
                recent = history.recently_output(
                    candidate.analysis.direction_key,
                    report_date,
                    self.settings.opportunity_cooldown_days,
                )
                item = scorer.score(
                    candidate,
                    occurrence_count=stats.occurrence_count,
                    source_count=stats.source_count,
                    first_seen=stats.first_seen,
                    last_seen=stats.last_seen,
                    recently_output=recent,
                )
                history.record_candidate(
                    candidate,
                    score=item.total_score,
                    prompt_version=prompt_version,
                    model=self.config.ai.model,
                    run_date=report_date,
                )
                scored.append(item)

            grouped = self._deduplicate_directions(scored)
            ranked = sorted(grouped, key=lambda item: item.total_score, reverse=True)
            signal_pool = [item for item in ranked if item.candidate.analysis.recommendation != "skip"]
            signals = [
                RadarSignal(
                    signal=item.candidate.analysis.signal,
                    why_now=item.candidate.analysis.why_now,
                    direction_key=item.candidate.analysis.direction_key,
                    score=item.total_score,
                    occurrence_count=item.occurrence_count,
                )
                for item in signal_pool[: self.settings.max_signals]
            ]
            opportunities = [
                item
                for item in ranked
                if item.candidate.analysis.recommendation == "pursue"
                and item.total_score >= self.settings.min_score
                and not item.recently_output
            ][: self.settings.max_opportunities]
            skipped = self._select_skipped(ranked)

            report = RadarReport(
                report_date=report_date,
                fetched_count=len(fetched),
                new_article_count=new_article_count,
                analyzed_count=len(batch.candidates),
                signals=signals,
                opportunities=opportunities,
                skipped=skipped,
                prompt_version=prompt_version,
                model=self.config.ai.model,
            )
            output_path, post_path = renderer.save(
                report,
                output_dir=self.settings.output_dir,
                docs_posts_dir=self.settings.docs_posts_dir,
            )
            for item in opportunities:
                history.mark_output(
                    item.candidate.analysis.direction_key,
                    item.candidate.article_hash,
                    report_date,
                )

        self.console.print(f"💾 Radar: {output_path}")
        self.console.print(f"📄 GitHub Pages: {post_path}")
        self.console.print(
            f"✅ Selected {len(opportunities)} opportunities and {len(skipped)} skip recommendations"
        )
        usage = get_usage_snapshot()
        if usage.total_tokens:
            self.console.print(
                f"🧮 Token usage: {usage.total_tokens} "
                f"(input {usage.total_input_tokens}, output {usage.total_output_tokens})"
            )
        return report

    async def _ensure_article_bodies(self, items: list[ContentItem]) -> int:
        """Fetch article bodies for short feed/HN records before AI analysis."""
        if not self.settings.extract_full_text:
            return 0
        extractor = TrafilaturaExtractor(
            TrafilaturaExtractorConfig(favor_precision=True)
        )
        semaphore = asyncio.Semaphore(self.settings.extractor_concurrency)
        extracted_count = 0

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            async def enrich(item: ContentItem) -> None:
                nonlocal extracted_count
                if len(item.content or "") >= self.settings.min_content_chars:
                    return
                if str(item.url).startswith("https://news.ycombinator.com/item"):
                    return
                async with semaphore:
                    full_text = await extractor.extract(str(item.url), client)
                if not full_text or len(full_text) <= len(item.content or ""):
                    return
                existing = item.content or ""
                item.content = full_text + (f"\n\n--- Source discussion ---\n{existing}" if existing else "")
                extracted_count += 1

            await asyncio.gather(*(enrich(item) for item in items))
        return extracted_count

    @staticmethod
    def _deduplicate_directions(items: list[ScoredOpportunity]) -> list[ScoredOpportunity]:
        grouped: dict[str, list[ScoredOpportunity]] = {}
        for item in items:
            grouped.setdefault(item.candidate.analysis.direction_key, []).append(item)
        result: list[ScoredOpportunity] = []
        for variants in grouped.values():
            variants.sort(key=lambda item: item.total_score, reverse=True)
            primary = variants[0].model_copy(deep=True)
            evidence = list(primary.candidate.analysis.evidence)
            for variant in variants[1:]:
                citation = f"{variant.candidate.source_title} — {variant.candidate.source_url}"
                if citation not in evidence:
                    evidence.append(citation)
            primary.candidate.analysis.evidence = evidence
            primary.occurrence_count = max(item.occurrence_count for item in variants)
            primary.source_count = max(item.source_count for item in variants)
            result.append(primary)
        return result

    def _select_skipped(self, ranked: list[ScoredOpportunity]) -> list[SkippedTrend]:
        candidates = [item for item in ranked if item.candidate.analysis.recommendation == "skip"]
        selected_ids = {id(item) for item in candidates}
        for item in reversed(ranked):
            if len(candidates) >= self.settings.max_skips:
                break
            if item.candidate.analysis.recommendation != "watch" or id(item) in selected_ids:
                continue
            candidates.append(item)
            selected_ids.add(id(item))
        result = []
        for item in candidates[: self.settings.max_skips]:
            analysis = item.candidate.analysis
            reason = analysis.not_recommended_reason or "当前证据、付费意愿或独立开发可行性仍不足，建议继续观察而非立即投入。"
            result.append(
                SkippedTrend(
                    signal=analysis.signal,
                    reason=reason,
                    source_title=item.candidate.source_title,
                    source_url=item.candidate.source_url,
                )
            )
        return result
