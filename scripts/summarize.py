#!/usr/bin/env python3
"""
AI 总结脚本
使用 Claude API 对论文摘要生成中文总结 + 每周综述标题

用法：
  python summarize.py            # 只总结无摘要的论文
  python summarize.py --all      # 重新总结所有论文
  python summarize.py --weekly   # 只生成每周综述标题
  python summarize.py --local    # 本地模式（跳过总结，留到本地运行）

关于 API Key 安全性：
  GitHub Actions Secrets 是加密存储的，运行时解密，日志自动屏蔽。
  只有仓库管理员才能查看 Secrets。这是业界标准做法。
  如果你仍想在本地运行总结，可以使用 --local 模式。
"""

import os
import json
import time
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict

from dotenv import load_dotenv
from anthropic import Anthropic, APIError, RateLimitError, APIConnectionError

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 200
BATCH_SIZE = 5
BATCH_DELAY = 3

SYSTEM_PROMPT = """你是一位渔业科学领域的学术编辑，精通中英文。将英文论文标题和摘要总结成简洁中文。

要求：
1. 2-4 句话概括：研究目的、方法、主要发现
2. 摘要缺失则根据标题用一句话简介
3. 语言专业简洁准确
4. 只输出总结文本，不加"本研究""这篇论文"等引导词
5. 保留关键术语英文原名（如 stock assessment）
6. 明显与渔业无关的内容输出"非渔业相关论文"

示例：
基于贝叶斯模型对北大西洋鳕鱼(Gadus morhua)进行种群评估，结合环境因子提高预测精度。结果显示水温升高导致鳕鱼补充量下降15-20%，建议降低捕捞配额。"""

WEEKLY_TOPIC_PROMPT = """你是渔业科学领域的学术主编。以下是一周内发表的渔业相关论文标题列表。

请根据这些论文标题，为本週渔业文献精选起一个概括性的中文标题（10-20字），概括本周的研究热点和趋势。

只输出标题，不要加引号、编号或其他修饰。标题要有信息量，能让读者一眼了解本周的研究主题。

示例输出：
气候变化下的渔业资源评估与适应性管理新进展"""


def get_client() -> Optional[Anthropic]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ 未设置 ANTHROPIC_API_KEY 环境变量")
        return None
    return Anthropic(api_key=api_key)


def load_papers() -> dict:
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        return {"papers": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_papers(data: dict):
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_week_key(date_str: str) -> str:
    """获取日期的周标识 (ISO 周: YYYY-WXX)"""
    if not date_str:
        return "未知"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except ValueError:
        return "未知"


def get_week_range(week_key: str) -> str:
    """将周标识转换为日期范围显示"""
    try:
        year, week = week_key.split("-W")
        year, week = int(year), int(week)
        # ISO 周的第一天是周一
        from datetime import date
        jan4 = date(year, 1, 4)
        first_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
        week_start = first_monday + timedelta(weeks=week - 1)
        week_end = week_start + timedelta(days=6)
        return f"{week_start.month}月{week_start.day}日 — {week_end.month}月{week_end.day}日"
    except Exception:
        return week_key


def summarize_paper(client: Anthropic, paper: dict) -> str:
    """调用 Claude API 总结单篇论文"""
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    user_message = f"标题：{title}\n\n摘要：{abstract}" if abstract else f"标题：{title}\n\n（无摘要）"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()
    except RateLimitError:
        time.sleep(10)
        try:
            response = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            return f"[总结失败: {e}]"
    except (APIConnectionError, APIError) as e:
        return f"[总结失败: {e}]"


def generate_weekly_topic(client: Anthropic, titles: list[str]) -> str:
    """为本周论文生成综述标题"""
    if not titles:
        return "暂无文献"

    # 取前 30 篇标题（避免 token 过多）
    titles_text = "\n".join(f"- {t}" for t in titles[:30])
    user_message = f"以下是一周内发表的渔业相关论文标题：\n\n{titles_text}"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=80,
            system=WEEKLY_TOPIC_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"    ⚠️ 周综述生成失败: {e}")
        return "渔业文献精选"


def summarize_papers(client: Anthropic, papers: list[dict], force_all: bool = False):
    """总结论文列表（增量：跳过已有总结的）"""
    unsolved = papers if force_all else [p for p in papers if not p.get("summary_cn", "").strip()]
    if not unsolved:
        print("✅ 所有论文已有总结")
        return

    total = len(unsolved)
    print(f"🤖 使用 {MODEL} 生成中文总结... ({total} 篇)\n")

    success = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = unsolved[batch_start : batch_start + BATCH_SIZE]
        for i, paper in enumerate(batch):
            idx = batch_start + i + 1
            title_short = paper["title"][:70] + "..." if len(paper["title"]) > 70 else paper["title"]
            print(f"  [{idx}/{total}] {title_short}")

            summary = summarize_paper(client, paper)
            paper["summary_cn"] = summary
            if summary and not summary.startswith("[总结失败"):
                success += 1
                print(f"    ✅ {summary[:80]}...")
            else:
                print(f"    ❌ {summary}")
            if i < len(batch) - 1:
                time.sleep(1)

        save_papers({"last_updated": "", "total_papers": 0, "new_today": 0, "papers": papers,
                      "weekly_topics": {}})
        remaining = total - batch_start - BATCH_SIZE
        if remaining > 0:
            print(f"\n  💾 进度 {min(batch_start + BATCH_SIZE, total)}/{total}，等待 {BATCH_DELAY}s...\n")
            time.sleep(BATCH_DELAY)

    print(f"\n✅ 论文总结完成: {success}/{total}")


def generate_all_weekly_topics(client: Anthropic, papers: list[dict]) -> dict:
    """为所有周生成综述标题"""
    # 按周分组
    weeks = defaultdict(list)
    for p in papers:
        wk = get_week_key(p.get("date", ""))
        weeks[wk].append(p["title"])

    topics = {}
    print(f"📅 生成每周综述标题... ({len(weeks)} 周)\n")
    for wk in sorted(weeks.keys(), reverse=True):
        titles = weeks[wk]
        week_range = get_week_range(wk)
        print(f"  → {wk} ({week_range}) — {len(titles)} 篇")
        topic = generate_weekly_topic(client, titles)
        topics[wk] = {
            "week_key": wk,
            "week_range": week_range,
            "topic": topic,
            "paper_count": len(titles),
        }
        print(f"    📌 {topic}")
        time.sleep(1)

    return topics


def main():
    force_all = "--all" in sys.argv
    weekly_only = "--weekly" in sys.argv
    local_mode = "--local" in sys.argv

    client = get_client()
    if not client:
        print("\n💡 关于 API Key 安全性：")
        print("   GitHub Actions Secrets 是加密存储的，运行时解密，日志中自动屏蔽。")
        print("   只有仓库管理员能查看。这是 GitHub 官方推荐的安全做法。")
        print("\n📋 本地运行方案：")
        print("   1. 在 .env 中设置 ANTHROPIC_API_KEY")
        print("   2. 运行: python scripts/summarize.py")
        print("   3. 运行: python scripts/generate_site.py")
        print("   4. git commit && git push")
        sys.exit(1)

    data = load_papers()
    papers = data.get("papers", [])
    if not papers:
        print("📭 没有论文数据，请先运行 fetch_papers.py")
        return

    weekly_topics = data.get("weekly_topics", {})

    if force_all:
        for p in papers:
            p["summary_cn"] = ""
        weekly_topics = {}

    if not weekly_only:
        summarize_papers(client, papers, force_all)

    # 生成/更新每周综述
    weekly_topics = generate_all_weekly_topics(client, papers)

    # 最终保存
    data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_papers": len(papers),
        "new_today": data.get("new_today", 0),
        "papers": papers,
        "weekly_topics": weekly_topics,
    }
    save_papers(data)
    print(f"\n✅ 全部完成！数据已保存: {DATA_FILE}")


if __name__ == "__main__":
    main()
