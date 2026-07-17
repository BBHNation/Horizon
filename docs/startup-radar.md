---
layout: default
title: Startup Radar
---

# Startup Radar 第一阶段

## 数据流

```text
RSS / Hacker News / Reddit / GitHub / GitHub Trending
                         ↓
                 Horizon 并发抓取
                         ↓
       Trafilatura 正文提取与 URL 去重
                         ↓
              固定 JSON Schema AI 分析
                         ↓
          SQLite 历史归并、趋势与输出冷却
                         ↓
                 确定性机会评分
                         ↓
             Renderer 生成《今日创业雷达》
```

第一阶段关闭 Telegram、Twitter/X、OpenBB、邮件、MCP 和双语日报。原模块仍保留在代码库中，后续可按需重新接入。

## 本地运行

准备配置和密钥：

```bash
cp data/config.example.json data/config.json
cp .env.example .env
```

编辑 `profile.yml` 后运行：

```bash
uv sync
uv run startup-radar --hours 24
```

强制重新分析 SQLite 中已有材料：

```bash
uv run startup-radar --hours 24 --reanalyze
```

输出位置：

- `data/radar/startup-radar-YYYY-MM-DD.md`
- `docs/_posts/YYYY-MM-DD-startup-radar.md`
- 历史数据库：`data/startup_radar.db`

## 评分

总分由程序计算，不由模型直接决定。评分维度包括痛点强度、用户规模、出现频率、现有方案成熟度、时机、AI 成本杠杆、独立开发适配度、个人匹配度、MVP 难度和证据可信度。

SQLite 中同一创业方向的重复出现次数和来源多样性会带来有限的趋势加分；近期已经输出过的方向默认冷却 7 天。Prompt 版本升级时，历史文章会自动按新 Schema 重新分析。

GitHub Actions 使用 `actions/cache` 在每日运行之间恢复和保存 `data/startup_radar.db`；本地 Cron 和 Docker 则通过持久化的 `data/` 目录保留历史。
