---
layout: default
title: Horizon 综合决策雷达
---

# Horizon 综合决策雷达

<div class="home-hero">
  <p class="eyebrow">NEWS · CONTEXT · OPPORTUNITY</p>
  <p class="lead">先用多源新闻看清宏观、政策、产业与社会变化，再判断哪些创业方向真正值得验证。</p>
</div>

<div class="quick-links">
  <a href="#今日综合新闻">
    <strong>阅读综合新闻</strong>
    <span>概述、影响、来源与完整分析</span>
  </a>
  <a href="#今日创业机会">
    <strong>查看创业机会</strong>
    <span>从变化中提炼机会与 7 天 MVP</span>
  </a>
  <a href="{{ '/sources/' | relative_url }}">
    <strong>查看信息源清单</strong>
    <span>每天各来源抓取了哪些文章</span>
  </a>
</div>

平台分两步回答问题：

- 综合新闻先归纳今天发生了什么、为什么重要、不同来源如何解释；
- 创业雷达再判断哪些变化值得个人或小团队在 7–14 天内验证。

## 今日综合新闻

<ul class="report-list">
  {% assign news_posts = site.posts | where: "category", "news-digest" %}
  {% for post in news_posts limit:30 %}
    <li>
      <a href="{{ post.url | relative_url }}">
        <span class="report-date">{{ post.date | date: "%Y-%m-%d" }}</span>
        <span class="report-meta">概述、多源证据与影响分析 →</span>
      </a>
    </li>
  {% else %}
    <li class="empty-state">尚未生成综合新闻报告。</li>
  {% endfor %}
</ul>

## 今日创业机会

<ul class="report-list">
  {% assign radar_posts = site.posts | where: "category", "startup-radar" %}
  {% for post in radar_posts limit:30 %}
    <li>
      <a href="{{ post.url | relative_url }}">
        <span class="report-date">{{ post.date | date: "%Y-%m-%d" }}</span>
        <span class="report-meta">查看机会、证据与验证路径 →</span>
      </a>
    </li>
  {% else %}
    <li class="empty-state">尚未生成创业雷达。</li>
  {% endfor %}
</ul>

## 文档

- [综合新闻报告与证据分层](news-digest)
- [每日信息源清单](sources/)
- [Startup Radar 架构与运行方式](startup-radar)
- [Horizon 信息源采集器](scrapers)
- [AI Provider 与环境变量配置](configuration)
