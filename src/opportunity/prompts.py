"""Centralized prompts for startup opportunity discovery."""

from __future__ import annotations

import json

from .schemas import DirectionResolution, OpportunityAnalysis, StartupProfile


PROMPT_VERSION = "startup-radar-v4"

OPPORTUNITY_ANALYSIS_SYSTEM = """你是独立开发者的创业机会研究员。

你的任务不是总结新闻，而是判断一条真实信息是否暴露了可验证、可行动的创业机会。

原则：
1. 从用户痛点和行为变化出发，不追逐空泛热点。
2. 区分“技术很热门”和“有人愿意付费解决问题”。
3. 优先考虑个人或小团队能在 7-14 天验证的机会。
4. personal_fit 必须严格依据给定的个人画像。
5. evidence 只能引用输入材料中确实存在的事实，不得编造数字、用户反馈或市场规模。
6. direction_key 使用简短、稳定、全小写的英文短语；同一创业方向即使新闻措辞不同也应得到相同 key。
7. recommendation=pursue 仅用于值得立即验证的机会；watch 表示信号尚弱；skip 表示热点但不适合投入。
8. solution_maturity 和 mvp_difficulty 越高代表越成熟/越困难，评分器会反向计分。
9. 只输出符合 JSON Schema 的 JSON，不要输出 Markdown 或额外说明。
10. 除 direction_key 外，所有文本字段必须使用简体中文；signal 要描述用户需求、行为或市场结构发生的变化，不要复述新闻标题或产品参数。
11. 以下情况默认 recommendation=skip：仅给新模型套一层通用聊天/Prompt UI、依赖模型价差的 API 转售、没有独特分发/数据/工作流的开源重打包、只能利用一次性 Bug 的产品。
12. 只有当机会拥有清晰的细分用户、重复痛点、可触达的首批用户和非模型本身的差异化时，才能 recommendation=pursue。
13. indie_advantage 解释为什么个人开发者能以速度、细分场景或低成本形成优势；business_model 只描述谁为什么付费。
14. 不得使用 no-opportunity、none、general-trend 等笼统 direction_key；即使 recommendation=skip，也要给出该热点本身的具体方向 key。
15. personal_fit_reason 必须点名个人画像中的具体技术能力、兴趣或约束，不能只说“匹配度高”。
"""

OPPORTUNITY_ANALYSIS_USER = """请结合个人画像分析下面这条材料。

个人画像：
{profile}

材料：
- 标题：{title}
- 来源：{source}
- 作者：{author}
- 发布时间：{published_at}
- URL：{url}
- 互动信息：{engagement}

正文：
{content}

输出 JSON Schema：
{schema}
"""

OPPORTUNITY_DEDUP_SYSTEM = """你负责创业机会方向的语义去重。

判断标准是目标用户、核心痛点和拟议产品是否本质相同，而不是新闻标题或技术名是否相同。
例如“AI 浏览器”和“Browser Agent”如果服务同一用户并解决同一浏览自动化问题，应归入同一方向。
优先复用已有历史方向 key；没有对应历史方向时，使用本批候选中最清晰稳定的 key。
必须为每个候选返回一个映射。只输出符合 JSON Schema 的 JSON，不要输出 Markdown。
不要因为多个候选都是 skip/watch 就把不相关热点合并；只有用户、痛点和产品方向三者高度相同才合并。
"""

OPPORTUNITY_DEDUP_USER = """历史创业方向：
{history}

本批候选：
{candidates}

输出 JSON Schema：
{schema}
"""


def build_analysis_prompt(
    *,
    profile: StartupProfile,
    title: str,
    source: str,
    author: str,
    published_at: str,
    url: str,
    engagement: str,
    content: str,
) -> str:
    return OPPORTUNITY_ANALYSIS_USER.format(
        profile=json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2),
        title=title,
        source=source,
        author=author,
        published_at=published_at,
        url=url,
        engagement=engagement or "无",
        content=content or "无正文，仅根据标题和来源谨慎判断。",
        schema=json.dumps(OpportunityAnalysis.model_json_schema(), ensure_ascii=False),
    )


def build_dedup_prompt(
    candidates: list[dict[str, object]],
    history: list[dict[str, str]],
) -> str:
    return OPPORTUNITY_DEDUP_USER.format(
        history=json.dumps(history, ensure_ascii=False, indent=2),
        candidates=json.dumps(candidates, ensure_ascii=False, indent=2),
        schema=json.dumps(DirectionResolution.model_json_schema(), ensure_ascii=False),
    )
