---
layout: default
title: 今日创业雷达
---

# Startup Radar

Startup Radar 基于 Horizon 的多来源采集能力，每天从新闻、产品和社区讨论中发现适合独立开发者验证的创业机会。

它不生成新闻摘要。每份报告只回答三个问题：

- 今天出现了哪些值得创业者关注的变化？
- 哪些机会适合个人或小团队在 7–14 天内验证？
- 哪些热门方向不值得投入？

## 今日创业雷达

<ul>
  {% assign radar_posts = site.posts | where: "category", "startup-radar" %}
  {% for post in radar_posts limit:30 %}
    <li>
      <a href="{{ post.url | relative_url }}">{{ post.date | date: "%Y-%m-%d" }}</a>
    </li>
  {% else %}
    <li><em>尚未生成创业雷达。</em></li>
  {% endfor %}
</ul>

## 文档

- [Startup Radar 架构与运行方式](startup-radar)
- [Horizon 信息源采集器](scrapers)
- [AI Provider 与环境变量配置](configuration)
