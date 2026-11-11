#!/usr/bin/env python3
"""每日抓取 OpenAI 与 Anthropic 博客/新闻动态，生成当天快照与新增清单。

用法: python scripts/fetch_blogs.py

输出:
  data/raw/YYYY-MM-DD.json    当天两家全部在架文章快照（is_new 标记今日新增）
  data/known_links.json       已见文章链接基线（增量对比用）
  data/articles_meta.json     文章元数据库（url -> 标题/日期/摘要，避免重复抓详情页）

首次运行为基线建立：仅把最近 7 天内发布的文章标记为 is_new，其余仅入库。
脚本幂等：同一天重复运行不会产生重复新增。
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
KNOWN_FILE = ROOT / "data" / "known_links.json"
META_FILE = ROOT / "data" / "articles_meta.json"

OPENAI_RSS = "https://openai.com/news/rss.xml"
ANTHROPIC_NEWS = "https://www.anthropic.com/news"

# Anthropic 列表页里的分类入口/导航链接，不是具体文章
ANTHROPIC_SKIP = {
    "announcements", "product", "features", "research", "policy", "company",
    "engineering", "safety", "education", "events", "index", "news",
}

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )
}

TODAY = datetime.now(timezone.utc).astimezone().date()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_openai() -> list:
    """OpenAI 走 RSS，条目自带完整元数据。"""
    root = ET.fromstring(fetch(OPENAI_RSS))
    arts = []
    for item in root.iter("item"):
        url = (item.findtext("link") or "").strip()
        if not url:
            continue
        pub = ""
        pub_raw = item.findtext("pubDate")
        if pub_raw:
            try:
                pub = parsedate_to_datetime(pub_raw).date().isoformat()
            except Exception:
                pass
        arts.append({
            "source": "openai",
            "title": (item.findtext("title") or "").strip(),
            "url": url,
            "published": pub,
            "category": (item.findtext("category") or "").strip(),
            "summary": html.unescape((item.findtext("description") or "").strip()),
        })
    return arts


def anthropic_links() -> list:
    """解析 Anthropic 新闻列表页，返回文章 URL（去重保序）。"""
    page = fetch(ANTHROPIC_NEWS)
    links = []
    for path, slug in re.findall(r'href="(/news/([a-z0-9-]+))"', page):
        if slug in ANTHROPIC_SKIP:
            continue
        url = "https://www.anthropic.com" + path
        if url not in links:
            links.append(url)
    return links


def anthropic_detail(url: str) -> dict:
    """抓 Anthropic 文章详情页 meta，提取标题/日期/摘要。"""
    try:
        page = fetch(url)
    except Exception:
        return {"title": url.rsplit("/", 1)[-1], "published": "", "summary": "", "category": ""}

    def meta(prop):
        m = re.search(r'<meta property="%s" content="([^"]*)"' % re.escape(prop), page)
        return html.unescape(m.group(1)).strip() if m else ""

    return {
        "title": meta("og:title") or url.rsplit("/", 1)[-1],
        "published": (meta("article:published_time") or "")[:10],
        "summary": meta("og:description"),
        "category": "",
    }


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    first_run = not KNOWN_FILE.exists()
    known = load_json(KNOWN_FILE, None) or {"openai": [], "anthropic": []}
    meta_db = load_json(META_FILE, {})

    articles, errors = [], []
    # 链接基线按全量记（防误报），快照只保留最近 90 天发布的条目
    known_updates = {"openai": [], "anthropic": []}

    try:
        arts = fetch_openai()
        cutoff = (TODAY - timedelta(days=90)).isoformat()
        for a in arts:
            meta_db[a["url"]] = a
            known_updates["openai"].append(a["url"])
            if not a.get("published") or a["published"] >= cutoff:
                articles.append(a)
    except Exception as e:
        errors.append(f"openai: {e!r}")

    try:
        for url in anthropic_links():
            if url in meta_db:
                a = dict(meta_db[url])
                a["url"] = url
            else:  # 新链接才抓详情页，日常每天只有几篇
                a = {"source": "anthropic", "url": url, **anthropic_detail(url)}
                meta_db[url] = a
            articles.append(a)
            known_updates["anthropic"].append(url)
    except Exception as e:
        errors.append(f"anthropic: {e!r}")

    # 标记新增：基线运行只报最近 7 天发布的；日常按链接是否见过判定
    baseline_days = (TODAY - timedelta(days=6)).isoformat()
    for a in articles:
        if first_run:
            pub = a.get("published") or ""
            a["is_new"] = bool(pub and pub >= baseline_days)
        else:
            a["is_new"] = a["url"] not in known[a["source"]]

    # 更新链接基线
    for src, urls in known_updates.items():
        for url in urls:
            if url not in known[src]:
                known[src].append(url)

    articles.sort(key=lambda a: (a.get("published") or "", a["source"]), reverse=True)
    snapshot = {
        "date": TODAY.isoformat(),
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "first_run": first_run,
        "errors": errors,
        "articles": articles,
    }
    snap_path = RAW_DIR / f"{TODAY}.json"
    save_json(snap_path, snapshot)
    save_json(KNOWN_FILE, known)
    save_json(META_FILE, meta_db)

    new_arts = [a for a in articles if a["is_new"]]
    n_by_src = {s: sum(1 for a in articles if a["source"] == s) for s in ("openai", "anthropic")}
    print(f"[fetch] date={TODAY} openai={n_by_src['openai']} anthropic={n_by_src['anthropic']} "
          f"new={len(new_arts)} first_run={first_run} errors={len(errors)}")
    for a in new_arts:
        print(f"[NEW] {a['source']:9s} {a.get('published', ''):10s} {a['title']}")
        print(f"      {a['url']}")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
    print(f"[fetch] snapshot -> {snap_path}")
    return 1 if len(errors) == 2 else 0  # 两家全挂才算彻底失败


if __name__ == "__main__":
    sys.exit(main())
