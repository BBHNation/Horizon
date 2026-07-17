"""End-to-end Startup Radar workflow built on Horizon's collection layer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import httpx
import yaml
from rich.console import Console

from .._file_utils import _atomic_write_text
from ..ai.client import create_ai_client
from ..ai.tokens import get_usage_snapshot
from ..extractors.trafilatura import TrafilaturaExtractor
from ..models import Config, ContentItem, TrafilaturaExtractorConfig
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import StorageManager
from .analyzer import OpportunityAnalyzer
from .history import HistoryStore
from .inventory import SourceInventoryWriter, source_group
from .prompts import PROMPT_VERSION, TRIAGE_PROMPT_VERSION
from .renderer import StartupRadarRenderer
from .schemas import (
    RadarReport,
    RadarSignal,
    ScoredOpportunity,
    SkippedTrend,
    StartupProfile,
    TriageDecision,
)
from .scorer import OpportunityScorer
from .triage import OpportunityTriage


_PAIN_TERMS = (
    "struggle",
    "frustrat",
    "pain",
    "annoy",
    "difficult",
    "expensive",
    "too much time",
    "manual",
    "wish there",
    "looking for",
    "alternative",
    "problem",
    "help",
    "痛点",
    "麻烦",
    "困难",
    "太贵",
    "耗时",
    "手动",
    "有没有",
    "求推荐",
    "替代",
    "问题",
    "需求",
)


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

    @staticmethod
    def _source_quota_group(item: ContentItem) -> str | None:
        """Map raw Horizon sources into the five Startup Radar source buckets."""
        group = source_group(item)
        return None if group == "other" else group

    def _select_by_source_quota(
        self,
        queued: list[tuple[ContentItem, str]],
        *,
        limit: int | None = None,
        scores: dict[str, float] | None = None,
    ) -> list[tuple[ContentItem, str]]:
        """Select a strict, non-backfilled daily analysis pool by source ratio."""
        target = limit or self.settings.max_articles_per_run
        groups: dict[str, list[tuple[ContentItem, str]]] = {
            name: [] for name in self.settings.source_quotas
        }
        for pair in queued:
            group = self._source_quota_group(pair[0])
            if group in groups:
                groups[group].append(pair)

        selected: list[tuple[ContentItem, str]] = []
        raw_limits = {
            group: target * ratio
            for group, ratio in self.settings.source_quotas.items()
        }
        limits = {group: math.floor(value) for group, value in raw_limits.items()}
        remainder = target - sum(limits.values())
        quota_order = list(self.settings.source_quotas)
        for group in sorted(
            quota_order,
            key=lambda name: (raw_limits[name] - limits[name], -quota_order.index(name)),
            reverse=True,
        )[:remainder]:
            limits[group] += 1

        for group in self.settings.source_quotas:
            selected.extend(
                self._balanced_group(groups[group], limits[group], group, scores=scores)
            )

        # Keep output order deterministic and make the strongest evidence enter
        # the concurrent analyzer first. Empty source buckets are intentionally
        # not backfilled, otherwise a transient source failure recreates tech bias.
        selected.sort(key=lambda pair: self._rank_key(pair, scores), reverse=True)
        return selected

    def _rank_key(
        self,
        pair: tuple[ContentItem, str],
        scores: dict[str, float] | None,
    ) -> tuple[float, float, float, float]:
        local = scores.get(pair[1], 0.0) if scores else 0.0
        return (local, *self._article_priority(pair[0]))

    def _balanced_group(
        self,
        candidates: list[tuple[ContentItem, str]],
        limit: int,
        group: str,
        *,
        scores: dict[str, float] | None = None,
    ) -> list[tuple[ContentItem, str]]:
        """Round-robin publishers/communities within a quota group."""
        if group == "hackernews":
            return sorted(
                candidates, key=lambda pair: self._rank_key(pair, scores), reverse=True
            )[:limit]

        pools: dict[str, list[tuple[ContentItem, str]]] = {}
        for pair in candidates:
            item = pair[0]
            if group == "reddit":
                key = str(item.metadata.get("subreddit") or "reddit")
            elif group == "rss":
                key = str(item.metadata.get("feed_name") or "rss")
            elif group == "google_news":
                key = str(item.metadata.get("source_name") or "google-news")
            else:
                key = str(item.metadata.get("feed_name") or item.source_type.value)
            pools.setdefault(key, []).append(pair)

        for pool in pools.values():
            pool.sort(key=lambda pair: self._rank_key(pair, scores), reverse=True)

        result: list[tuple[ContentItem, str]] = []
        while len(result) < limit:
            current_round = [pool.pop(0) for pool in pools.values() if pool]
            if not current_round:
                break
            current_round.sort(
                key=lambda pair: self._rank_key(pair, scores), reverse=True
            )
            result.extend(current_round[: limit - len(result)])
        return result

    def _local_scores(
        self,
        articles: list[tuple[ContentItem, str]],
        profile: StartupProfile,
        *,
        window_hours: int,
    ) -> dict[str, float]:
        """Token-free opportunity heuristics normalized within each source group."""
        now = datetime.now(timezone.utc)
        engagement: dict[str, float] = {}
        by_group: dict[str, list[tuple[str, float]]] = {}
        for item, article_hash in articles:
            raw = self._raw_engagement(item)
            engagement[article_hash] = raw
            group = self._source_quota_group(item) or "other"
            by_group.setdefault(group, []).append((article_hash, raw))

        engagement_percentile: dict[str, float] = {}
        for values in by_group.values():
            ordered = sorted(values, key=lambda pair: pair[1])
            if not ordered or ordered[-1][1] <= 0:
                engagement_percentile.update({article_hash: 0.25 for article_hash, _ in ordered})
                continue
            denominator = max(1, len(ordered) - 1)
            engagement_percentile.update(
                {article_hash: index / denominator for index, (article_hash, _) in enumerate(ordered)}
            )

        profile_terms = [
            str(value).strip().lower()
            for value in (*profile.technical_strengths, *profile.interested_domains)
            if str(value).strip()
        ]
        result: dict[str, float] = {}
        for item, article_hash in articles:
            text = f"{item.title}\n{(item.content or '')[:1800]}".lower()
            age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
            recency = max(0.0, 1 - age_hours / max(1, window_hours)) * 20
            content_quality = min(len(item.content or "") / 1200, 1) * 15
            pain_hits = sum(text.count(term) for term in _PAIN_TERMS)
            pain_score = min(20.0, pain_hits * 3.0)
            profile_hits = sum(term in text for term in profile_terms)
            profile_score = min(15.0, profile_hits * 5.0)
            question_score = 5.0 if any(mark in text for mark in ("?", "？", "how do", "what can")) else 0.0
            engagement_score = engagement_percentile[article_hash] * 25
            result[article_hash] = round(
                recency
                + content_quality
                + pain_score
                + profile_score
                + question_score
                + engagement_score,
                2,
            )
        return result

    @staticmethod
    def _raw_engagement(item: ContentItem) -> float:
        values = (
            item.metadata.get("score"),
            item.metadata.get("num_comments"),
            item.metadata.get("descendants"),
            item.metadata.get("stars_gained"),
            item.metadata.get("stars"),
            item.metadata.get("views"),
        )
        total = 0.0
        for value in values:
            try:
                total += max(0.0, float(value or 0))
            except (TypeError, ValueError):
                continue
        return math.log1p(total)

    @staticmethod
    def _normalized_title(title: str) -> str:
        return re.sub(r"[^\w\u3400-\u9fff]+", "", title.lower())

    def _remove_near_title_duplicates(
        self,
        articles: list[tuple[ContentItem, str]],
        scores: dict[str, float],
    ) -> tuple[list[tuple[ContentItem, str]], int]:
        ordered = sorted(articles, key=lambda pair: scores.get(pair[1], 0), reverse=True)
        kept: list[tuple[ContentItem, str]] = []
        normalized: list[str] = []
        for pair in ordered:
            candidate = self._normalized_title(pair[0].title)
            duplicate = any(
                candidate == existing
                or (
                    min(len(candidate), len(existing)) >= 18
                    and SequenceMatcher(None, candidate, existing).ratio() >= 0.90
                )
                for existing in normalized
            )
            if duplicate:
                continue
            kept.append(pair)
            normalized.append(candidate)
        return kept, len(articles) - len(kept)

    @staticmethod
    def _triage_cache_version(profile: StartupProfile) -> str:
        payload = json.dumps(
            profile.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        fingerprint = hashlib.sha256(payload).hexdigest()[:12]
        return f"{TRIAGE_PROMPT_VERSION}:{fingerprint}"

    @staticmethod
    def _fallback_triage(article_hash: str, local_score: float) -> TriageDecision:
        value = max(0.0, min(10.0, local_score / 10))
        return TriageDecision(
            article_id=article_hash,
            pain_signal=value,
            opportunity_relevance=value,
            novelty=max(0.0, value - 1),
            evidence_quality=value,
            personal_fit=value,
            direction_key=f"local-fallback-{article_hash[:12]}",
            reason="AI 初筛失败，暂按本地规则分保守排序。",
        )

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
        self.console.print(f"📥 Fetched {len(fetched)} items → {len(deduped)} URL-unique materials\n")
        if deduped:
            inventory_json, inventory_markdown = SourceInventoryWriter().save(
                deduped,
                report_date=report_date,
                output_dir=self.settings.output_dir,
            )
            self.console.print(f"🗂️  Source inventory: {inventory_markdown}")
            self.console.print(f"   JSON: {inventory_json}\n")

        ai_client = create_ai_client(self.config.ai)
        analyzer = OpportunityAnalyzer(ai_client, profile, self.console)
        scorer = OpportunityScorer()
        renderer = StartupRadarRenderer()

        with HistoryStore(self.settings.database_path) as history:
            prompt_version = self.settings.prompt_version or PROMPT_VERSION
            eligible: list[tuple[ContentItem, str]] = []
            new_article_count = 0
            for item in deduped:
                article_hash, is_new = history.add_article(item)
                new_article_count += int(is_new)
                if reanalyze or not history.was_analyzed(article_hash, prompt_version):
                    eligible.append((item, article_hash))

            local_scores = self._local_scores(
                eligible,
                profile,
                window_hours=hours,
            )
            if len(eligible) > self.settings.max_raw_items:
                eligible = self._select_by_source_quota(
                    eligible,
                    limit=self.settings.max_raw_items,
                    scores=local_scores,
                )
            unique_titles, near_duplicate_count = self._remove_near_title_duplicates(
                eligible,
                local_scores,
            )
            prefiltered = self._select_by_source_quota(
                unique_titles,
                limit=self.settings.prefilter_max_items,
                scores=local_scores,
            )
            self.console.print(
                f"🧹 Local zero-token filter: {len(eligible)} eligible → "
                f"{len(unique_titles)} title-unique → {len(prefiltered)} for AI triage "
                f"({near_duplicate_count} near-duplicates removed)\n"
            )

            triage_version = self._triage_cache_version(profile)
            decisions: dict[str, TriageDecision] = {}
            uncached: list[tuple[ContentItem, str]] = []
            for item, article_hash in prefiltered:
                cached = history.get_triage(
                    article_hash,
                    triage_version,
                    self.config.ai.model,
                )
                if cached is None:
                    uncached.append((item, article_hash))
                else:
                    decisions[article_hash] = cached

            if self.settings.triage_enabled and uncached:
                self.console.print(
                    f"🔎 DeepSeek compact triage: {len(prefiltered)} materials "
                    f"({len(decisions)} cached, {len(uncached)} new)\n"
                )
                triage = OpportunityTriage(
                    ai_client,
                    profile,
                    batch_size=self.settings.triage_batch_size,
                    excerpt_chars=self.settings.triage_excerpt_chars,
                    max_tokens=self.settings.triage_max_tokens,
                    concurrency=self.settings.triage_concurrency,
                    console=self.console,
                )
                triage_result = await triage.score(uncached)
                decisions.update(triage_result.decisions)
                for article_hash, decision in triage_result.decisions.items():
                    history.record_triage(
                        article_hash,
                        triage_version,
                        self.config.ai.model,
                        decision,
                    )
                for failure in triage_result.failures:
                    self.console.print(f"[yellow]⚠️  {failure}[/yellow]")

            for _, article_hash in prefiltered:
                if article_hash not in decisions:
                    decisions[article_hash] = self._fallback_triage(
                        article_hash,
                        local_scores.get(article_hash, 0.0),
                    )

            local_weight = self.settings.local_score_weight
            combined_scores = {
                article_hash: round(
                    decision.ai_score * (1 - local_weight)
                    + local_scores.get(article_hash, 0.0) * local_weight,
                    2,
                )
                for article_hash, decision in decisions.items()
            }
            queued = self._select_by_source_quota(
                prefiltered,
                scores=combined_scores,
            )
            source_counts = {
                group: sum(
                    self._source_quota_group(item) == group for item, _ in queued
                )
                for group in self.settings.source_quotas
            }
            audit_path = self._save_selection_audit(
                report_date=report_date,
                fetched_count=len(fetched),
                deduped_count=len(deduped),
                eligible_count=len(eligible),
                near_duplicate_count=near_duplicate_count,
                prefiltered=prefiltered,
                selected=queued,
                local_scores=local_scores,
                decisions=decisions,
                combined_scores=combined_scores,
                source_counts=source_counts,
            )
            if audit_path:
                self.console.print(f"🧾 Selection audit: {audit_path}\n")
            extracted_count = await self._ensure_article_bodies(
                [item for item, _ in queued]
            )
            if extracted_count:
                self.console.print(
                    f"📄 Extracted full text for {extracted_count} selected short materials\n"
                )
            for item, _ in queued:
                history.add_article(item)
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
                deduped_count=len(deduped),
                new_article_count=new_article_count,
                prefiltered_count=len(prefiltered),
                triaged_count=len(decisions),
                analyzed_count=len(batch.candidates),
                source_counts=source_counts,
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

    def _save_selection_audit(
        self,
        *,
        report_date: date,
        fetched_count: int,
        deduped_count: int,
        eligible_count: int,
        near_duplicate_count: int,
        prefiltered: list[tuple[ContentItem, str]],
        selected: list[tuple[ContentItem, str]],
        local_scores: dict[str, float],
        decisions: dict[str, TriageDecision],
        combined_scores: dict[str, float],
        source_counts: dict[str, int],
    ) -> Path | None:
        if not self.settings.selection_audit:
            return None

        selected_hashes = {article_hash for _, article_hash in selected}
        materials = []
        for item, article_hash in sorted(
            prefiltered,
            key=lambda pair: combined_scores.get(pair[1], 0.0),
            reverse=True,
        ):
            decision = decisions[article_hash]
            materials.append(
                {
                    "article_hash": article_hash,
                    "status": "selected_for_deep_analysis"
                    if article_hash in selected_hashes
                    else "not_selected_after_triage",
                    "source_group": self._source_quota_group(item),
                    "source_type": item.source_type.value,
                    "title": item.title,
                    "url": str(item.url),
                    "local_score": local_scores.get(article_hash, 0.0),
                    "ai_triage_score": decision.ai_score,
                    "combined_score": combined_scores.get(article_hash, 0.0),
                    "triage_reason": decision.reason,
                    "direction_key": decision.direction_key,
                }
            )

        payload = {
            "report_date": report_date.isoformat(),
            "funnel": {
                "fetched": fetched_count,
                "url_unique": deduped_count,
                "eligible_unanalyzed": eligible_count,
                "near_title_duplicates_removed": near_duplicate_count,
                "local_prefiltered": len(prefiltered),
                "deep_analysis_selected": len(selected),
            },
            "selected_source_counts": source_counts,
            "materials": materials,
        }
        audit_dir = Path(self.settings.output_dir) / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"selection-audit-{report_date.isoformat()}.json"
        _atomic_write_text(
            audit_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        return audit_path

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
