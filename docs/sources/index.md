---
layout: default
title: 信息源清单
permalink: /sources/
---

<nav class="page-actions" aria-label="页面导航">
  <a href="{{ '/' | relative_url }}">← 返回首页</a>
  <a href="{{ '/startup-radar' | relative_url }}">了解雷达方法</a>
</nav>

# 信息源清单

这里展示每天抓取并完成 URL 去重后的全部材料，用来检查信息覆盖范围和来源偏差。清单不等于送入 AI 深度分析的材料；进入深度分析的内容还会经过本地预筛、AI 初筛和来源配额选择。

{% assign inventories = site.pages | where: "source_inventory", true | sort: "date" | reverse %}

<ul class="report-list source-archive">
{% for inventory in inventories %}
  <li>
    <a href="{{ inventory.url | relative_url }}">
      <span class="report-date">{{ inventory.date | date: "%Y-%m-%d" }}</span>
      <span class="report-meta">{{ inventory.source_total }} 条去重材料</span>
    </a>
  </li>
{% else %}
  <li class="empty-state">尚未生成信息源清单。下一次 Startup Radar 成功运行后会自动出现在这里。</li>
{% endfor %}
</ul>
