#!/usr/bin/env python3
"""
HTML 站点生成脚本
从论文数据生成每周摘要布局的静态 HTML 页面
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict, OrderedDict

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "docs"
OUTPUT_FILE = OUTPUT_DIR / "index.html"


def load_data() -> dict:
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_week_key(date_str: str) -> str:
    """获取 ISO 周标识"""
    if not date_str:
        return "未知"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except ValueError:
        return "未知"


def get_week_range(week_key: str) -> str:
    """周标识 → 中文日期范围"""
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
        return f"{week_start.month}月{week_start.day}日 — {week_end.month}月{week_end.day}日"
    except Exception:
        return week_key


def get_summary_count(papers: list[dict]) -> int:
    count = 0
    for p in papers:
        s = p.get("summary_cn", "").strip()
        if s and not s.startswith("[总结失败") and not s.startswith("["):
            count += 1
    return count


def get_journal_count(papers: list[dict]) -> int:
    journals = set()
    for p in papers:
        j = p.get("journal", "").strip()
        if j:
            journals.add(j.lower())
    return len(journals)


def generate():
    print("📖 加载论文数据...")
    data = load_data()
    papers = data.get("papers", [])
    weekly_topics = data.get("weekly_topics", {})

    print(f"📊 总计 {len(papers)} 篇论文")

    # 按周分组
    week_groups = OrderedDict()
    for paper in papers:
        wk = get_week_key(paper.get("date", ""))
        if wk not in week_groups:
            week_groups[wk] = []
        week_groups[wk].append(paper)

    # 构建每周数据
    weeks = []
    for wk in sorted(week_groups.keys(), reverse=True):
        papers_in_week = week_groups[wk]
        # 组内按期刊名排序
        papers_in_week.sort(key=lambda x: x.get("journal", ""))

        # 获取该周的综述标题
        topic_info = weekly_topics.get(wk, {})
        topic = topic_info.get("topic", "") if isinstance(topic_info, dict) else str(topic_info)
        if not topic:
            # 用论文数生成默认标题
            topic = f"渔业文献精选 · {len(papers_in_week)} 篇"

        weeks.append({
            "week_key": wk,
            "week_range": get_week_range(wk),
            "topic": topic,
            "papers": papers_in_week,
        })

    # 更新时间
    update_time = data.get("last_updated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        ut = datetime.strptime(update_time, "%Y-%m-%dT%H:%M:%SZ")
        update_display = ut.strftime("%Y年%m月%d日 %H:%M UTC")
    except ValueError:
        update_display = update_time

    context = {
        "update_time": update_display,
        "total_papers": len(papers),
        "week_count": len(weeks),
        "summary_count": get_summary_count(papers),
        "journal_count": get_journal_count(papers),
        "weeks": weeks,
    }

    # 渲染
    print("🎨 渲染 HTML 模板...")
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("index.html.jinja2")
    html = template.render(**context)

    # 写入
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    file_size = OUTPUT_FILE.stat().st_size
    print(f"✅ HTML 已生成: {OUTPUT_FILE} ({file_size / 1024:.1f} KB)")
    print(f"   - {len(weeks)} 个周分组")
    print(f"   - {get_summary_count(papers)} 篇有 AI 中文总结")
    print(f"   - {get_journal_count(papers)} 个不同期刊")


if __name__ == "__main__":
    generate()
