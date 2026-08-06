from datetime import date, datetime, timezone

from src.models import ContentItem, NewsDigestConfig, SourceType
from src.news.analyzer import NewsDigestAnalyzer
from src.news.renderer import NewsDigestRenderer
from src.news.schemas import DailyNewsReport, NewsDigestDraft
from src.news.selector import NewsMaterialSelector


def item(
    index: int,
    publisher: str,
    *,
    category: str = "macro-economy",
    tier: str = "professional",
    source_type: SourceType = SourceType.RSS,
    preferred: bool = False,
) -> ContentItem:
    return ContentItem(
        id=f"rss:test:{index}",
        source_type=source_type,
        title=f"News {index}",
        url=f"https://example.com/{index}",
        content=f"Material {index}",
        author=publisher,
        published_at=datetime(2026, 8, 3, index % 24, tzinfo=timezone.utc),
        metadata={
            "feed_name": publisher,
            "category": category,
            "source_tier": tier,
            "preferred": preferred,
        },
    )


def test_selector_caps_publishers_and_community_ratio():
    settings = NewsDigestConfig(
        max_input_items=10,
        max_items_per_publisher=2,
        community_max_ratio=0.1,
    )
    materials = [item(i, "Same Publisher") for i in range(6)]
    materials += [item(10 + i, f"Publisher {i}", category="technology") for i in range(5)]
    materials += [
        item(
            20 + i,
            f"Community {i}",
            tier="community",
            source_type=SourceType.REDDIT,
        )
        for i in range(4)
    ]

    selected = NewsMaterialSelector(settings).select(materials)

    assert sum(value.metadata["feed_name"] == "Same Publisher" for value in selected) == 2
    assert sum(value.source_type == SourceType.REDDIT for value in selected) <= 1


def test_hydrate_events_ignores_unknown_and_duplicate_source_ids():
    settings = NewsDigestConfig(max_events=3)
    analyzer = NewsDigestAnalyzer(object(), settings)
    materials = [item(1, "新华社", tier="official", preferred=True), item(2, "BBC")]
    draft = NewsDigestDraft.model_validate(
        {
            "overview": "概述",
            "key_points": ["重点"],
            "events": [
                {
                    "title": "事件",
                    "category": "宏观经济",
                    "importance": 90,
                    "confidence": "high",
                    "summary": "摘要",
                    "confirmed_facts": ["事实"],
                    "why_it_matters": "重要",
                    "watch_next": ["数据"],
                    "source_ids": [1, 1, 2, 99],
                }
            ],
        }
    )

    events = analyzer.hydrate_events(draft, materials)

    assert [source.source_id for source in events[0].sources] == [1, 2]
    assert events[0].sources[0].source_tier == "official"
    assert events[0].sources[0].preferred is True


def test_hydrate_events_labels_single_professional_and_official_differently():
    settings = NewsDigestConfig(max_events=3)
    analyzer = NewsDigestAnalyzer(object(), settings)
    materials = [item(1, "联合早报"), item(2, "最高人民法院", tier="official")]
    base = {
        "category": "政策监管",
        "importance": 80,
        "confidence": "medium",
        "summary": "摘要",
        "confirmed_facts": ["事实"],
        "why_it_matters": "重要",
        "watch_next": [],
    }
    draft = NewsDigestDraft.model_validate(
        {
            "overview": "概述",
            "key_points": ["重点"],
            "events": [
                {**base, "title": "媒体单独报道", "source_ids": [1]},
                {**base, "title": "官方原始发布", "source_ids": [2]},
            ],
        }
    )

    events = analyzer.hydrate_events(draft, materials)

    assert [event.title for event in events] == ["官方原始发布", "媒体单独报道"]
    assert events[0].confidence == "medium"
    assert events[0].evidence_status == "primary"
    assert events[1].confidence == "low"
    assert events[1].evidence_status == "single_source"


def test_publisher_aliases_do_not_create_false_corroboration():
    assert NewsDigestAnalyzer.publisher_key("BBC World") == "bbc"
    assert NewsDigestAnalyzer.publisher_key("BBC Business") == "bbc"
    assert NewsDigestAnalyzer.publisher_key("新华网") == "xinhua"


def test_renderer_outputs_overview_details_sources_and_safe_links(tmp_path):
    settings = NewsDigestConfig()
    analyzer = NewsDigestAnalyzer(object(), settings)
    materials = [item(1, "新华社", tier="official", preferred=True), item(2, "BBC")]
    draft = NewsDigestDraft.model_validate(
        {
            "overview": "今天的总体变化",
            "key_points": ["先看宏观"],
            "events": [
                {
                    "title": "政策与市场发生变化",
                    "category": "政策监管",
                    "importance": 88,
                    "confidence": "high",
                    "summary": "事件摘要",
                    "confirmed_facts": ["事实一"],
                    "why_it_matters": "会影响决策",
                    "macro_impact": "宏观影响",
                    "industry_impact": "行业影响",
                    "individual_impact": "个人影响",
                    "different_views": "不同媒体侧重点不同",
                    "watch_next": ["观察下一次数据发布"],
                    "source_ids": [1, 2],
                }
            ],
        }
    )
    report = DailyNewsReport(
        report_date=date(2026, 8, 3),
        fetched_count=100,
        deduped_count=90,
        selected_count=40,
        publisher_count=12,
        corroborated_event_count=1,
        overview=draft.overview,
        key_points=draft.key_points,
        events=analyzer.hydrate_events(draft, materials),
        prompt_version="news-digest-v1",
        model="test-model",
    )

    markdown, json_path, post = NewsDigestRenderer().save(
        report,
        output_dir=tmp_path / "news",
        docs_posts_dir=tmp_path / "posts",
    )
    rendered = markdown.read_text()

    assert 'class="news-overview-data"' in rendered
    assert 'class="news-event__detail"' in rendered
    assert "查看 2 个来源" in rendered
    assert "偏好媒体" in rendered
    assert 'target="_blank" rel="noopener noreferrer"' in rendered
    assert json_path.exists()
    assert "category: news-digest" in post.read_text()
