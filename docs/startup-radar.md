---
layout: default
title: Startup Radar
---

# Startup Radar 第一阶段

## 数据流

```text
Reddit / 多领域 RSS / Google News / Hacker News / GitHub 与 OSS Insight
                         ↓
                 Horizon 并发抓取
                         ↓
             URL 与近似标题零 Token 去重
                         ↓
       本地规则评分并按来源配额预筛约 60 条
                         ↓
        DeepSeek 批量读取短摘要做轻量初筛
                         ↓
        按来源配额选 20 条并提取完整正文
                         ↓
              固定 JSON Schema 深度分析
                         ↓
          SQLite 历史归并、趋势与输出冷却
                         ↓
                 确定性机会评分
                         ↓
             Renderer 生成《今日创业雷达》
```

第一阶段关闭 Telegram、Twitter/X、OpenBB、邮件、MCP 和双语日报。原模块仍保留在代码库中，后续可按需重新接入。

## 来源比例

每天最多选 20 条材料送入 AI，配额固定为：

- Reddit 用户痛点：6 条（30%）
- 多领域 RSS：6 条（30%）
- Google News 商业/消费变化：4 条（20%）
- Hacker News：3 条（15%）
- GitHub / OSS Insight：1 条（5%）

某组当天材料不足时不会用其他组补齐，以免 Reddit 或商业源暂时不可用时又被技术内容占满。通过 RSS 接入的 GitHub Trending 会归到 GitHub / OSS Insight 组，不占多领域 RSS 配额。

同一组内也会做来源轮转：RSS 尽量平均覆盖不同订阅源，Reddit 尽量覆盖不同社区，Google News 尽量覆盖不同媒体，避免单个高频来源包揽该组名额。

## Token 控制与选材漏斗

默认参数：

- 原始候选上限：200 条
- 本地预筛上限：60 条
- DeepSeek 初筛批次：每批 15 条，每条只发送标题、约 320 字摘要和少量互动信息
- 深度分析：20 条，提取正文后逐条输出严格 JSON
- 本地规则分占最终选材分的 20%，AI 初筛分占 80%

本地阶段不调用模型，使用 URL、近似标题、时效、内容完整度、来源内互动百分位、痛点词和 `profile.yml` 匹配度完成去重与预筛。DeepSeek 初筛结果按“文章 Hash + 初筛 Prompt 版本 + 模型 + 画像指纹”缓存在 SQLite，同一条件下不会重复消耗 Token。

每次运行会额外写入：

```text
data/radar/audit/selection-audit-YYYY-MM-DD.json
data/radar/sources/source-inventory-YYYY-MM-DD.json
data/radar/sources/source-inventory-YYYY-MM-DD.md
```

审计文件记录抓取漏斗、来源配额、60 条候选的本地分、AI 初筛分、综合分、入选状态和简短理由。

信息源清单保留本次所有 URL 去重后的抓取结果，而不只是进入 AI 初筛的材料。JSON 和 Markdown 都包含来源分组、具体社区/订阅源/媒体、标题、原文链接、发布时间、分类和 Google News 查询词，便于回顾来源偏差并调整配置与 `profile.yml`。

当前启用的普通 RSS 是：

- 36氪文章资讯：商业、公司、消费与产品变化
- Simon Willison：AI 产品与工具

此外 GitHub Trending Daily 也使用 RSS 协议抓取，但在比例计算中属于 GitHub / OSS Insight。`data/config.github.json` 额外启用了 Semianalysis；本地 `data/config.json` 未启用它。

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
