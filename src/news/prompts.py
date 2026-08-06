"""Prompts for event-level, multi-source news synthesis."""

from __future__ import annotations

import json

from ..models import ContentItem


NEWS_DIGEST_SYSTEM = """你是一个严谨的中文新闻编辑和研究员。你的任务不是逐篇摘要，而是把描述同一事件的材料归并成事件，并清楚区分事实、媒体解释和仍待验证的观点。

硬性规则：
1. 只能使用输入材料，不得补充未提供的数字、引语或事实。
2. source_ids 只能引用输入中存在的编号；每个事件优先引用两个或更多独立发布者。
3. 官方公告和机构原文用于确认事实；专业媒体用于补充背景和不同地区视角；社区内容只能作为零星案例或灵感。
4. 不要把多家媒体对同一通讯社稿件的转载误判为多个独立证据。
5. 如果只有单一来源，confidence 不得为 high，并在 different_views 中说明尚缺交叉验证。
6. 不要展开或展示推理过程，直接输出简体中文 JSON，不要输出 Markdown 或解释文字。
7. 专业媒体事件优先引用至少两个独立发布者；如果确有价值但只有一个专业媒体来源，可以保留为单源观察，但 confidence 必须为 low，different_views 必须说明未交叉验证。单个社区材料不得成为新闻事件。source_tier 为 official 或 primary 的原始发布可单独成项，但要说明仍待后续跟踪。
8. confirmed_facts 只能写材料直接支持的事实，不得把标题中的提问、评论或因果推断改写成已确认事实。
"""


def build_news_digest_prompt(
    items: list[ContentItem],
    *,
    categories: list[str],
    max_events: int,
    excerpt_chars: int,
) -> str:
    materials = []
    for index, item in enumerate(items, 1):
        metadata = item.metadata
        materials.append(
            {
                "source_id": index,
                "publisher": (
                    metadata.get("source_name")
                    or metadata.get("feed_name")
                    or item.author
                    or item.source_type.value
                ),
                "source_type": item.source_type.value,
                "source_tier": metadata.get("source_tier"),
                "preferred": bool(metadata.get("preferred")),
                "category_hint": metadata.get("category"),
                "title": item.title,
                "published_at": item.published_at.isoformat(),
                "content": " ".join((item.content or "").split())[:excerpt_chars],
            }
        )

    schema = {
        "overview": "用两三句话概括今天最重要的整体变化",
        "key_points": ["3-6条一句话重点"],
        "events": [
            {
                "title": "事件标题",
                "category": categories[0],
                "importance": 85,
                "confidence": "high|medium|low",
                "summary": "先讲清发生了什么",
                "confirmed_facts": ["已被材料支持的事实"],
                "why_it_matters": "为什么值得关注",
                "macro_impact": "宏观层面影响，没有则为空字符串",
                "industry_impact": "行业或公司层面影响",
                "individual_impact": "对普通人、从业者或创业者的影响",
                "different_views": "不同来源的解释差异或证据局限",
                "watch_next": ["接下来值得观察的指标或节点"],
                "source_ids": [1, 2],
            }
        ],
    }
    return (
        f"请从以下材料中选出最多 {max_events} 个真正重要且彼此不同的事件。"
        f"分类只能使用：{'、'.join(categories)}。优先宏观经济、政策监管及会影响行业和个人决策的变化；"
        "在材料充分时兼顾产业公司、科技产品和消费社会。单源专业媒体只作为观察，不得写成已被多方确认的趋势。\n\n"
        "输出结构：\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n\n输入材料：\n"
        + json.dumps(materials, ensure_ascii=False)
    )
