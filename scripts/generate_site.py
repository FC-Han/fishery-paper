#!/usr/bin/env python3
"""
HTML 站点生成脚本
生成多页面架构：
  - docs/index.html          → 主页（每周综述卡片）
  - docs/week-2026-W25.html  → 每周论文详情页
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import OrderedDict

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "docs"


def load_data() -> dict:
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_week_key(date_str: str) -> str:
    if not date_str:
        return "未知"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except ValueError:
        return "未知"


def get_week_range(week_key: str) -> str:
    try:
        parts = week_key.split("-W")
        if len(parts) != 2:
            return week_key
        year, week = int(parts[0]), int(parts[1])
        jan4 = datetime(year, 1, 4)
        first_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
        week_start = first_monday + timedelta(weeks=week - 1)
        week_end = week_start + timedelta(days=6)
        today = datetime.now()
        if week_end > today:
            week_end = today
        return f"{week_start.month}月{week_start.day}日—{week_end.month}月{week_end.day}日"
    except Exception:
        return week_key


def parse_keywords(keywords_str: str) -> list[str]:
    """解析逗号分隔的关键词字符串为列表"""
    if not keywords_str:
        return []
    kws = [kw.strip() for kw in keywords_str.replace("，", ",").split(",")]
    return [kw for kw in kws if kw][:8]


def markdown_to_html(text: str) -> str:
    """将 AI 生成的综述文章从简单 Markdown 转为 HTML"""
    import re
    lines = text.strip().split("\n")
    html_lines = []
    in_list = False
    list_tag = ""

    for line in lines:
        stripped = line.strip()

        # 标题 ## Heading
        if stripped.startswith("## "):
            if in_list:
                html_lines.append(f"</{list_tag}>")
                in_list = False
            heading = stripped[3:]
            html_lines.append(f'<h2>{heading}</h2>')

        # 有序列表 1. item
        elif re.match(r"^\d+\.\s", stripped):
            if not in_list or list_tag != "ol":
                if in_list:
                    html_lines.append(f"</{list_tag}>")
                html_lines.append("<ol>")
                in_list = True
                list_tag = "ol"
            item = re.sub(r"^\d+\.\s+", "", stripped)
            # 加粗处理
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item)
            html_lines.append(f"<li>{item}</li>")

        # 空行
        elif not stripped:
            if in_list:
                html_lines.append(f"</{list_tag}>")
                in_list = False
            html_lines.append("")

        # 普通段落
        else:
            if in_list:
                html_lines.append(f"</{list_tag}>")
                in_list = False
            # 加粗处理
            para = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
            html_lines.append(f"<p>{para}</p>")

    if in_list:
        html_lines.append(f"</{list_tag}>")

    return "\n".join(html_lines)


def get_summary_count(papers: list[dict]) -> int:
    count = 0
    for p in papers:
        s = p.get("summary_cn", "").strip()
        if s and not s.startswith("[失败") and not s.startswith("["):
            count += 1
    return count


def get_journal_count(papers: list[dict]) -> int:
    journals = set()
    for p in papers:
        j = p.get("journal", "").strip()
        if j:
            journals.add(j.lower())
    return len(journals)


def build_weeks(papers: list[dict], weekly_topics: dict) -> list[dict]:
    """构建每周数据"""
    week_groups = OrderedDict()
    for paper in papers:
        wk = get_week_key(paper.get("date", ""))
        if wk not in week_groups:
            week_groups[wk] = []
        week_groups[wk].append(paper)

    weeks = []
    for wk in sorted(week_groups.keys(), reverse=True):
        papers_in_week = week_groups[wk]
        papers_in_week.sort(key=lambda x: x.get("journal", ""))

        topic_info = weekly_topics.get(wk, {})
        if isinstance(topic_info, dict):
            topic = topic_info.get("topic", "")
            keywords = topic_info.get("keywords", "")
            article = topic_info.get("article", "")
            high_impact_count = topic_info.get("high_impact_count", 0)
        else:
            topic = str(topic_info) if topic_info else ""
            keywords = ""
            article = ""
            high_impact_count = 0

        if not topic:
            topic = f"渔业文献精选 · {len(papers_in_week)} 篇"

        keywords_list = parse_keywords(keywords)

        weeks.append({
            "week_key": wk,
            "week_range": get_week_range(wk),
            "topic": topic,
            "keywords": keywords,
            "keywords_list": keywords_list,
            "article": article,
            "article_html": markdown_to_html(article) if article else "",
            "high_impact_count": high_impact_count,
            "papers": papers_in_week,
        })

    return weeks


def generate():
    print("📖 加载论文数据...")
    data = load_data()
    papers = data.get("papers", [])
    weekly_topics = data.get("weekly_topics", {})

    print(f"📊 {len(papers)} 篇论文")

    weeks = build_weeks(papers, weekly_topics)

    # 格式化更新时间
    update_time = data.get("last_updated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        ut = datetime.strptime(update_time, "%Y-%m-%dT%H:%M:%SZ")
        update_display = ut.strftime("%Y年%m月%d日 %H:%M UTC")
    except ValueError:
        update_display = update_time

    # Jinja2 环境
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    # === 生成主页 ===
    print("\n🏠 生成主页...")
    index_context = {
        "update_time": update_display,
        "total_papers": len(papers),
        "week_count": len(weeks),
        "summary_count": get_summary_count(papers),
        "journal_count": get_journal_count(papers),
        "weeks": weeks,
    }
    index_template = env.get_template("index.html.jinja2")
    index_html = index_template.render(**index_context)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index_path = OUTPUT_DIR / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"  ✅ {index_path} ({len(index_html) / 1024:.0f} KB)")

    # === 生成每周详情页 ===
    print(f"\n📄 生成 {len(weeks)} 个周详情页...")
    week_template = env.get_template("week.html.jinja2")
    for week in weeks:
        wk = week["week_key"]
        summary_in_week = sum(1 for p in week["papers"]
                             if p.get("summary_cn","").strip() and not p.get("summary_cn","").startswith("["))
        week_context = {
            "week": week,
            "update_time": update_display,
            "summary_count": summary_in_week,
        }
        week_html = week_template.render(**week_context)
        week_path = OUTPUT_DIR / f"week-{wk}.html"
        with open(week_path, "w", encoding="utf-8") as f:
            f.write(week_html)
        print(f"  ✅ week-{wk}.html ({len(week_html) / 1024:.0f} KB) — {len(week['papers'])} 篇")

    print(f"\n🎉 全部完成！")
    print(f"   主页: {OUTPUT_DIR / 'index.html'}")
    print(f"   周页: {OUTPUT_DIR / 'week-*.html'} 共 {len(weeks)} 个")


if __name__ == "__main__":
    generate()
