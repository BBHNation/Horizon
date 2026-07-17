from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from src.models import Config, ContentItem, SourceType
from src.opportunity.analyzer import OpportunityAnalyzer
from src.opportunity.history import HistoryStore
from src.opportunity.inventory import SourceInventoryWriter
from src.opportunity.orchestrator import StartupRadarOrchestrator
from src.opportunity.renderer import StartupRadarRenderer
from src.opportunity.schemas import (
    OpportunityAnalysis,
    OpportunityCandidate,
    RadarReport,
    RadarSignal,
    ScoredOpportunity,
    SkippedTrend,
    StartupProfile,
    TriageDecision,
)
from src.opportunity.scorer import OpportunityScorer
from src.opportunity.triage import OpportunityTriage
from src.storage.manager import StorageManager


def make_item(suffix: str = "1", source: SourceType = SourceType.RSS) -> ContentItem:
    return ContentItem(
        id=f"test:{suffix}",
        source_type=source,
        title=f"Developers struggle with repetitive security review {suffix}",
        url=f"https://example.com/story/{suffix}",
        content="Several solo developers describe losing hours to repetitive security checks.",
        author="author",
        published_at=datetime.now(timezone.utc),
    )


def make_analysis(**overrides) -> OpportunityAnalysis:
    payload = {
        "signal": "独立开发者需要轻量安全审查",
        "direction_key": "indie-security-review",
        "target_user": "独立开发者和两三人的产品团队",
        "pain_point": "发布前缺少低成本、可操作的安全检查。",
        "current_solution": "企业工具昂贵，手工检查耗时。",
        "why_now": "AI 降低了代码与配置审查的边际成本。",
        "business_model": "按项目订阅，先聚焦一个框架。",
        "indie_advantage": "可以从单一框架切入，用速度和垂直场景避开企业平台。",
        "personal_fit": 9,
        "personal_fit_reason": "软件安全与 Web 能力可直接用于构建该工具，且符合单人开发约束。",
        "confidence": "high",
        "evidence": ["多名开发者报告相同问题"],
        "seven_day_mvp": "上传仓库并返回十项优先修复建议。",
        "first_users": "独立开发者社区和开源项目维护者。",
        "risks": ["误报会损害信任"],
        "recommendation": "pursue",
        "not_recommended_reason": "",
        "score_dimensions": {
            "pain_intensity": 9,
            "user_scale": 7,
            "occurrence_frequency": 8,
            "solution_maturity": 3,
            "why_now_strength": 9,
            "ai_cost_leverage": 9,
            "indie_suitability": 9,
            "personal_match": 9,
            "mvp_difficulty": 3,
            "evidence_credibility": 8,
        },
    }
    payload.update(overrides)
    return OpportunityAnalysis.model_validate(payload)


def make_candidate(item: ContentItem, article_hash: str = "hash-1", **analysis_overrides):
    return OpportunityCandidate(
        analysis=make_analysis(**analysis_overrides),
        article_hash=article_hash,
        source_title=item.title,
        source_url=str(item.url),
        source_type=item.source_type.value,
        published_at=item.published_at,
    )


class FakeAIClient:
    config = None

    async def complete(self, **_kwargs):
        return make_analysis().model_dump_json()


class FakeDirectionClient:
    config = None

    async def complete(self, **_kwargs):
        return json.dumps(
            {
                "mappings": [
                    {"candidate_index": 0, "canonical_key": "browser-agent"},
                    {"candidate_index": 1, "canonical_key": "browser-agent"},
                ]
            }
        )


class FakeTriageClient:
    config = None

    async def complete(self, **kwargs):
        article_ids = re.findall(r'"article_id":"([a-f0-9-]+)"', kwargs["user"])
        return json.dumps(
            {
                "items": [
                    {
                        "article_id": article_id,
                        "pain_signal": 8,
                        "opportunity_relevance": 7,
                        "novelty": 6,
                        "evidence_quality": 8,
                        "personal_fit": 9,
                        "direction_key": "indie-security-review",
                        "reason": "材料包含明确且重复出现的用户痛点。",
                    }
                    for article_id in article_ids
                ]
            },
            ensure_ascii=False,
        )


def test_analyzer_returns_validated_candidate():
    item = make_item()
    analyzer = OpportunityAnalyzer(
        FakeAIClient(),
        StartupProfile(technical_strengths=["软件安全"]),
    )
    candidate = asyncio.run(analyzer.analyze_one(item, "article-hash"))
    assert candidate.analysis.direction_key == "indie-security-review"
    assert candidate.analysis.personal_fit == 9
    assert candidate.article_hash == "article-hash"


def test_direction_aliases_merge_new_wording_into_historical_direction():
    first_item = make_item("browser")
    second_item = make_item("agent")
    candidates = [
        make_candidate(first_item, "browser", direction_key="ai-browser"),
        make_candidate(second_item, "agent", direction_key="browser-agent"),
    ]
    analyzer = OpportunityAnalyzer(FakeDirectionClient(), StartupProfile())
    asyncio.run(
        analyzer.resolve_direction_aliases(
            candidates,
            [{"direction_key": "browser-agent", "signal": "浏览器自动化代理"}],
        )
    )
    assert {item.analysis.direction_key for item in candidates} == {"browser-agent"}


def test_compact_triage_scores_every_material_in_batches():
    articles = [(make_item(str(index)), f"abc-{index}") for index in range(5)]
    triage = OpportunityTriage(
        FakeTriageClient(),
        StartupProfile(technical_strengths=["软件安全"]),
        batch_size=2,
        excerpt_chars=120,
    )
    result = asyncio.run(triage.score(articles))
    assert len(result.decisions) == 5
    assert result.failures == []
    assert result.decisions["abc-0"].ai_score == 76.0


def test_scorer_rewards_solution_gap_and_easy_mvp():
    item = make_item()
    scorer = OpportunityScorer()
    easy = make_candidate(item)
    hard = make_candidate(
        item,
        article_hash="hash-2",
        score_dimensions={
            **easy.analysis.score_dimensions.model_dump(),
            "solution_maturity": 9,
            "mvp_difficulty": 9,
        },
    )
    assert scorer.base_score(easy) > scorer.base_score(hard)
    assert scorer.history_boost(4, 3) > scorer.history_boost(1, 1)


def test_schema_rejects_english_only_narrative():
    with pytest.raises(ValueError, match="signal must contain Simplified Chinese"):
        make_analysis(signal="Developers need a safer coding agent")


def test_history_tracks_articles_directions_and_output_cooldown(tmp_path):
    first = make_item("1", SourceType.RSS)
    second = make_item("2", SourceType.HACKERNEWS)
    run_date = date(2026, 7, 17)
    with HistoryStore(tmp_path / "radar.db") as history:
        first_hash, first_is_new = history.add_article(first)
        _, first_is_new_again = history.add_article(first)
        second_hash, _ = history.add_article(second)
        assert first_is_new is True
        assert first_is_new_again is False

        first_candidate = make_candidate(first, first_hash)
        second_candidate = make_candidate(second, second_hash)
        history.record_candidate(
            first_candidate,
            score=80,
            prompt_version="v1",
            model="fake",
            run_date=run_date - timedelta(days=1),
        )
        history.record_candidate(
            second_candidate,
            score=82,
            prompt_version="v1",
            model="fake",
            run_date=run_date,
        )
        stats = history.event_stats("indie-security-review")
        assert stats.occurrence_count == 2
        assert stats.source_count == 2

        history.mark_output("indie-security-review", first_hash, run_date - timedelta(days=1))
        assert history.recently_output("indie-security-review", run_date, 7) is True

        triage = TriageDecision(
            article_id=first_hash,
            pain_signal=8,
            opportunity_relevance=7,
            novelty=6,
            evidence_quality=8,
            personal_fit=9,
            direction_key="indie-security-review",
            reason="材料包含明确用户痛点。",
        )
        history.record_triage(first_hash, "triage-v1:profile", "fake", triage)
        cached = history.get_triage(first_hash, "triage-v1:profile", "fake")
        assert cached == triage


def test_full_text_extraction_replaces_short_feed_content(tmp_path, monkeypatch):
    config = Config.model_validate(
        {
            "ai": {
                "provider": "openai",
                "model": "fake",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {"hackernews": {"enabled": False}},
            "filtering": {"time_window_hours": 24},
            "startup_radar": {"min_content_chars": 1200},
        }
    )
    item = make_item()
    item.content = "short discussion"

    async def fake_extract(_self, _url, _client):
        return "完整正文" * 800

    monkeypatch.setattr(
        "src.opportunity.orchestrator.TrafilaturaExtractor.extract", fake_extract
    )
    orchestrator = StartupRadarOrchestrator(
        config,
        StorageManager(str(tmp_path / "data")),
        profile_path=tmp_path / "profile.yml",
    )
    count = asyncio.run(orchestrator._ensure_article_bodies([item]))
    assert count == 1
    assert item.content.startswith("完整正文")
    assert "short discussion" in item.content


def test_source_quota_selects_exact_30_30_20_15_5_split(tmp_path):
    config = Config.model_validate(
        {
            "ai": {
                "provider": "openai",
                "model": "fake",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {"hackernews": {"enabled": False}},
            "filtering": {"time_window_hours": 24},
            "startup_radar": {"max_articles_per_run": 20},
        }
    )
    orchestrator = StartupRadarOrchestrator(
        config,
        StorageManager(str(tmp_path / "data")),
        profile_path=tmp_path / "profile.yml",
    )
    queued = []
    source_groups = (
        (SourceType.REDDIT, "reddit", None),
        (SourceType.RSS, "rss", "business-consumer"),
        (SourceType.GOOGLE_NEWS, "google_news", None),
        (SourceType.HACKERNEWS, "hackernews", None),
        (SourceType.OSSINSIGHT, "developer", None),
    )
    for source, group, category in source_groups:
        for index in range(10):
            item = make_item(f"{group}-{index}", source)
            if category:
                item.metadata["category"] = category
            queued.append((item, f"hash-{group}-{index}"))

    github_trending = make_item("github-rss", SourceType.RSS)
    github_trending.metadata["category"] = "github-trending"
    assert orchestrator._source_quota_group(github_trending) == "developer"

    selected = orchestrator._select_by_source_quota(queued)
    counts = {
        group: sum(orchestrator._source_quota_group(item) == group for item, _ in selected)
        for _, group, _ in source_groups
    }
    assert counts == {
        "reddit": 6,
        "rss": 6,
        "google_news": 4,
        "hackernews": 3,
        "developer": 1,
    }


def test_source_quota_balances_feeds_within_rss_slice(tmp_path):
    config = Config.model_validate(
        {
            "ai": {
                "provider": "openai",
                "model": "fake",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {"hackernews": {"enabled": False}},
            "filtering": {"time_window_hours": 24},
        }
    )
    orchestrator = StartupRadarOrchestrator(
        config,
        StorageManager(str(tmp_path / "data")),
        profile_path=tmp_path / "profile.yml",
    )
    queued = []
    for feed_name in ("36氪 - 文章资讯", "Simon Willison"):
        for index in range(10):
            item = make_item(f"{feed_name}-{index}", SourceType.RSS)
            item.metadata["feed_name"] = feed_name
            queued.append((item, f"hash-{feed_name}-{index}"))

    selected = orchestrator._select_by_source_quota(queued)
    feed_counts = {
        feed_name: sum(item.metadata.get("feed_name") == feed_name for item, _ in selected)
        for feed_name in ("36氪 - 文章资讯", "Simon Willison")
    }
    assert feed_counts == {"36氪 - 文章资讯": 3, "Simon Willison": 3}


def test_source_inventory_keeps_source_title_and_link(tmp_path):
    reddit = make_item("reddit", SourceType.REDDIT)
    reddit.metadata.update({"subreddit": "smallbusiness", "category": "business-pain"})
    rss = make_item("rss", SourceType.RSS)
    rss.metadata.update({"feed_name": "36氪 - 文章资讯", "category": "business-consumer"})

    json_path, markdown_path = SourceInventoryWriter().save(
        [reddit, rss],
        report_date=date(2026, 7, 17),
        output_dir=tmp_path,
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total"] == 2
    assert {item["source"] for item in payload["items"]} == {
        "r/smallbusiness",
        "36氪 - 文章资讯",
    }
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "| 来源 | 标题 | 链接 | 分类 |" in markdown
    assert "https://example.com/story/reddit" in markdown


def test_renderer_outputs_radar_sections_and_not_raw_json():
    item = make_item()
    candidate = make_candidate(item)
    now = datetime.now(timezone.utc)
    scored = ScoredOpportunity(
        candidate=candidate,
        total_score=82,
        base_score=80,
        history_boost=2,
        occurrence_count=2,
        source_count=2,
        first_seen=now,
        last_seen=now,
    )
    report = RadarReport(
        report_date=date(2026, 7, 17),
        fetched_count=20,
        deduped_count=19,
        new_article_count=18,
        prefiltered_count=12,
        triaged_count=12,
        analyzed_count=18,
        signals=[
            RadarSignal(
                signal=candidate.analysis.signal,
                why_now=candidate.analysis.why_now,
                direction_key=candidate.analysis.direction_key,
                score=82,
                occurrence_count=2,
            )
        ],
        opportunities=[scored],
        skipped=[
            SkippedTrend(
                signal="通用 AI 套壳",
                reason="差异化不足",
                source_title="A hot launch",
                source_url="https://example.com/hot",
            )
        ],
        prompt_version="v1",
        model="fake",
    )
    markdown = StartupRadarRenderer().render(report)
    assert "## 今天最值得关注" in markdown
    assert "## 今日创业机会" in markdown
    assert "## 今日不建议追" in markdown
    assert "7 天 MVP" in markdown
    assert "软件安全与 Web 能力" in markdown
    assert "选材漏斗" in markdown
    assert '"direction_key"' not in markdown
