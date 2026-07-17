---
layout: default
title: 今日创业雷达
---

# Startup Radar

<div class="home-hero">
  <p class="eyebrow">DAILY OPPORTUNITY BRIEFING</p>
  <p class="lead">每天从新闻、产品和社区讨论中，发现适合独立开发者验证的创业机会。</p>
</div>

<div class="quick-links">
  <a href="#今日创业雷达">
    <strong>阅读创业雷达</strong>
    <span>机会、证据与 7 天 MVP</span>
  </a>
  <a href="{{ '/sources/' | relative_url }}">
    <strong>查看信息源清单</strong>
    <span>每天各来源抓取了哪些文章</span>
  </a>
</div>

每份报告聚焦三个问题：

- 今天出现了哪些值得创业者关注的变化？
- 哪些机会适合个人或小团队在 7–14 天内验证？
- 哪些热门方向不值得投入？

## 今日创业雷达

<ul class="report-list">
  {% assign radar_posts = site.posts | where: "category", "startup-radar" %}
  {% for post in radar_posts limit:30 %}
    <li>
      <a href="{{ post.url | relative_url }}">
        <span class="report-date">{{ post.date | date: "%Y-%m-%d" }}</span>
        <span class="report-meta">查看当日机会与证据 →</span>
      </a>
    </li>
  {% else %}
    <li class="empty-state">尚未生成创业雷达。</li>
  {% endfor %}
</ul>

## 文档

- [每日信息源清单](sources/)
- [Startup Radar 架构与运行方式](startup-radar)
- [Horizon 信息源采集器](scrapers)
- [AI Provider 与环境变量配置](configuration)
