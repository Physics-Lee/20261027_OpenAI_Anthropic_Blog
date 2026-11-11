# OpenAI & Anthropic 博客监控

每日自动监控 [OpenAI News](https://openai.com/news) 与 [Anthropic Newsroom](https://www.anthropic.com/news) 的新文章，生成中文日报、周报、月报。

## 目录结构

```
├── scripts/
│   └── fetch_blogs.py        # 抓取脚本（幂等，可随时手动重跑）
├── data/
│   ├── raw/                  # 每日快照 YYYY-MM-DD.json（在架文章 + is_new 标记）
│   ├── known_links.json      # 已见文章链接基线（增量判定用）
│   └── articles_meta.json    # 文章元数据库（避免重复抓详情页）
└── reports/
    ├── daily/                # 日报   YYYY-MM-DD.md
    ├── weekly/               # 周报   区间首尾日期.md（每周一覆盖上周）
    └── monthly/              # 月报   YYYY-MM.md（每月 1 号覆盖上月）
```

## 数据源与抓取方式

| 来源 | 方式 | 说明 |
| --- | --- | --- |
| OpenAI | RSS `https://openai.com/news/rss.xml` | 自带标题/日期/摘要/分类；快照只保留近 90 天条目 |
| Anthropic | 新闻列表页 + 新文章详情页 meta | 无 RSS；用链接基线对比发现新增，仅对新增链接抓取详情页（og:title / og:description / article:published_time） |

首次运行（2026-10-27）建立基线：把近 7 天内发布的文章标记为新增，其余仅入库。之后每天"新增 = 链接首次出现"。

## 定时任务

单个自动化（每天 09:00 本地时间运行），按当天日期自动分流：

| 报告 | 生成时机 | 输出 |
| --- | --- | --- |
| 日报 | 每天 | `reports/daily/YYYY-MM-DD.md` |
| 周报 | 每周一（覆盖上周一~上周日） | `reports/weekly/起始日_结束日.md` |
| 月报 | 每月 1 号（覆盖上个自然月） | `reports/monthly/YYYY-MM.md` |

## 手动使用

```bash
# 只抓数据、刷新今天快照（重跑安全，不会产生重复"新增"）
python scripts/fetch_blogs.py

# 补某一天的报告：读 data/raw/ 对应日期快照，按 reports/ 下已有报告的格式手写
```

快照 JSON 结构：`{date, fetched_at, first_run, errors, articles: [{source, title, url, published, category, summary, is_new}]}`。
