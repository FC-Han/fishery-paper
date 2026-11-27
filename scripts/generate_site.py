#!/usr/bin/env python3
"""
站点生成脚本（单页应用版）

输出：
  docs/index.html            ← 自包含单页（数据内联，标签筛选全在前端完成）
  docs/data/abstracts.json   ← 英文摘要，点击时懒加载
  docs/data/papers.json      ← 完整数据（供二次开发/API 取用）

用法：
  python generate_site.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "docs"
DATA_OUT = OUTPUT_DIR / "data"

RETENTION_DAYS = 120
BJT = timezone(timedelta(hours=8))
SITE_URL = "https://fc-han.github.io/fishery-paper/"
FEED_TITLE = "Fishery Digest · 渔业文献每日速览"

WDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_data() -> dict:
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_lexicon(data: dict) -> list:
    lex = data.get("tag_lexicon")
    if lex:
        return lex
    sys.path.insert(0, str(ROOT / "scripts"))
    from tag_papers import lexicon  # type: ignore
    return lexicon()


def visible_papers(papers: list) -> list:
    """站点只展示与渔业科学相关的论文"""
    keep = []
    for p in papers:
        if not p.get("doi") or not p.get("title") or not p.get("date"):
            continue
        if p.get("off_topic"):
            continue
        keep.append(p)
    keep.sort(key=lambda x: x.get("date", ""), reverse=True)
    return keep


def short_abs(abstract: str, n: int = 220) -> str:
    """无中文摘要时，截取英文摘要首段做兜底展示"""
    a = (abstract or "").strip()
    if a.upper().startswith("ABSTRACT"):
        a = a[8:].strip()
    if len(a) <= n:
        return a
    cut = a[:n]
    for sep in (". ", "; "):
        idx = cut.rfind(sep)
        if idx > n * 0.5:
            return cut[:idx + 1]
    return cut.rstrip() + "…"


def slim(p: dict) -> dict:
    """内联到 HTML 的精简记录（不含完整英文摘要）"""
    cn = (p.get("summary_cn") or "").strip()
    usable_cn = cn and not cn.startswith("[") and "非渔业相关" not in cn
    return {
        "doi": p.get("doi", ""),
        "title": p.get("title", ""),
        "authors": p.get("authors", ""),
        "journal": p.get("journal", ""),
        "date": p.get("date", ""),
        "summary": cn if usable_cn else short_abs(p.get("abstract", "")),
        "summary_en": not usable_cn,
        "url": p.get("url") or f"https://doi.org/{p.get('doi', '')}",
        "tags": p.get("tags", {}),
        "rel": p.get("rel") or [],
        "is_review": bool(p.get("is_review")),
        "high_impact": bool(p.get("high_impact")),
    }


def rfc822(date_str: str) -> str:
    """2026-11-27 → Fri, 27 Nov 2026 08:00:00 +0800（不用 strftime 的 %a/%b，避免受系统 locale 影响）"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJT) + timedelta(hours=8)
    except ValueError:
        dt = datetime.now(BJT)
    return (f"{WDAY[dt.weekday()]}, {dt.day:02d} {MON[dt.month - 1]} {dt.year} "
            f"{dt.hour:02d}:{dt.minute:02d}:00 +0800")


def cdata(text: str) -> str:
    return "<![CDATA[" + (text or "").replace("]]>", "]]&gt;") + "]]>"


def build_feed(papers: list, zh_of: dict, limit: int = 80) -> str:
    """最近 80 条（论文已按日期倒序）生成 RSS 2.0，供 RSS 阅读器 / 邮件订阅服务抓取"""
    items = []
    for p in papers[:limit]:
        zh_tags = [zh_of.get((d, t), t)
                   for d in ("theme", "species", "region")
                   for t in (p.get("tags", {}).get(d) or [])][:5]
        head = " · ".join(x for x in [p.get("journal", ""), p.get("date", "")] if x)
        body = (p.get("summary_cn") or "").strip()
        if not body or body.startswith("[") or "非渔业相关" in body:
            body = short_abs(p.get("abstract", ""), 300)
        desc = f"{head}\n\n{body}"
        if zh_tags:
            desc += "\n\n标签：" + "、".join(zh_tags)
        link = p.get("url") or f"https://doi.org/{p.get('doi', '')}"
        items.append(
            "    <item>\n"
            f"      <title>{escape(p.get('title', ''))}</title>\n"
            f"      <link>{escape(link)}</link>\n"
            f'      <guid isPermaLink="false">{escape(p.get("doi", ""))}</guid>\n'
            f"      <pubDate>{rfc822(p.get('date', ''))}</pubDate>\n"
            f"      <description>{cdata(desc)}</description>\n"
            + "".join(f"      <category>{escape(t)}</category>\n" for t in zh_tags) +
            "    </item>"
        )

    build = rfc822(papers[0]["date"]) if papers else rfc822("")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{escape(FEED_TITLE)}</title>\n"
        f"    <link>{SITE_URL}</link>\n"
        "    <description>每天自动抓取渔业 / 水产 / 海洋领域新论文，AI 中文速览 + 多维标签</description>\n"
        "    <language>zh-CN</language>\n"
        f"    <lastBuildDate>{build}</lastBuildDate>\n"
        f'    <atom:link href="{SITE_URL}feed.xml" rel="self" type="application/rss+xml"/>\n'
        + "\n".join(items) + "\n"
        "  </channel>\n"
        "</rss>\n"
    )


def main():
    data = load_data()
    papers = visible_papers(data.get("papers", []))
    if not papers:
        print("❌ 没有可展示的论文")
        sys.exit(1)

    lexicon = build_lexicon(data)

    dates = sorted({p["date"] for p in papers})
    journals = {p.get("journal", "").strip().lower() for p in papers if p.get("journal")}
    tag_kinds = len({(t["dim"], t["id"]) for t in lexicon})

    last_updated = data.get("last_updated", "")
    try:
        ut = datetime.strptime(last_updated, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        update_display = ut.astimezone(BJT).strftime("%Y年%m月%d日 %H:%M（北京时间）")
    except (ValueError, AttributeError):
        update_display = last_updated or "—"

    payload = {
        "generated_at": last_updated,
        "count": len(papers),
        "lexicon": lexicon,
        "papers": [slim(p) for p in papers],
    }

    # 关联索引化：doi → 数组下标，比内联完整 doi 省一个数量级体积
    doi2i = {p["doi"]: i for i, p in enumerate(payload["papers"])}
    edges = 0
    for item in payload["papers"]:
        rel = item.get("rel") or []
        # 第 4 位仅在「弱关联」（无一篇过阈值时的兜底）出现
        item["rel"] = [[doi2i[r["d"]], r["s"], "|".join(r.get("t") or [])]
                       + ([1] if r.get("w") else [])
                       for r in rel if r.get("d") in doi2i]
        edges += len(item["rel"])

    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = (data_json.replace("</", "<\\/")
                          .replace("\u2028", "\\u2028")
                          .replace("\u2029", "\\u2029"))

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("app.html.jinja2")
    html = tpl.render(
        data_json=data_json,
        update_display=update_display,
        journal_total=len(journals),
        retention_days=RETENTION_DAYS,
        embed_api=os.environ.get("EMBED_ENDPOINT", "").strip(),
        ask_api=os.environ.get("ASK_ENDPOINT", "").strip(),
        site_url=SITE_URL,
        feed_url=SITE_URL + "feed.xml",
        stats={
            "papers": len(papers),
            "days": len(dates),
            "journals": len(journals),
            "tag_kinds": tag_kinds,
        },
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    index_path = OUTPUT_DIR / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {index_path.relative_to(ROOT)}  ({len(html.encode('utf-8')) / 1024:.0f} KB)")

    abstracts = {p["doi"]: p.get("abstract", "") for p in papers if p.get("abstract")}
    abs_path = DATA_OUT / "abstracts.json"
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(abstracts, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ {abs_path.relative_to(ROOT)}  ({abs_path.stat().st_size / 1024:.0f} KB, {len(abstracts)} 条)")

    api_path = DATA_OUT / "papers.json"
    with open(api_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"✅ {api_path.relative_to(ROOT)}  ({api_path.stat().st_size / 1024:.0f} KB)")

    zh_of = {(t["dim"], t["id"]): t["zh"] for t in lexicon}
    feed_path = OUTPUT_DIR / "feed.xml"
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(build_feed(papers, zh_of))
    print(f"✅ {feed_path.relative_to(ROOT)}  ({feed_path.stat().st_size / 1024:.0f} KB, 最近 80 条)")

    print(f"\n📊 {len(papers)} 篇 · {len(dates)} 天 · {len(journals)} 本期刊 · {tag_kinds} 种标签")


if __name__ == "__main__":
    main()
