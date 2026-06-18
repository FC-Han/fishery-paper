#!/usr/bin/env python3
"""
AI 总结脚本 (DeepSeek API)
对论文摘要生成中文总结 + 每周综述标题 + 每周关键词

用法：
  python summarize.py            # 增量总结新论文
  python summarize.py --all      # 重新总结所有论文
  python summarize.py --weekly   # 只更新每周综述和关键词
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
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

# DeepSeek 配置
DEEPSEEK_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"
MAX_TOKENS_SUMMARY = 300
MAX_TOKENS_TOPIC = 100
MAX_TOKENS_KEYWORDS = 100
BATCH_SIZE = 8
BATCH_DELAY = 2

# 提示词：论文中文总结
SUMMARY_SYSTEM = """你是渔业科学学术编辑。将英文论文标题和摘要总结为简洁中文。

要求：
1. 2-4句话概括：研究目的、方法、主要发现
2. 摘要缺失则根据标题写一句话简介
3. 语言专业简洁，面向渔业研究者
4. 只输出总结文本，不加任何引导词
5. 关键术语保留英文（如 stock assessment, MPA）
6. 明显与渔业无关的内容输出「非渔业相关」"""

# 提示词：每周综述标题
WEEKLY_TOPIC_SYSTEM = """你是渔业科学主编。根据本周论文标题，起一个中文综述标题（10-20字），概括本周研究热点和趋势。

只输出标题本身，不加引号、编号或任何修饰。标题要有信息量。

示例：气候变化下渔业资源评估新方法与适应性管理进展"""

# 提示词：每周关键词
WEEKLY_KEYWORDS_SYSTEM = """你是渔业科学编辑。从本周论文标题中提取5-8个研究关键词。

要求：
1. 关键词用中文，括号附英文术语
2. 涵盖本周主要研究方向和热点
3. 按重要性排序
4. 每个关键词2-6字
5. 只输出关键词，用逗号分隔，一行输出

示例格式：
种群评估(Stock Assessment), 气候变化(Climate Change), 水产养殖(Aquaculture), MPI保护区, 兼捕减少, 生态系统模型"""


def get_client() -> Optional[OpenAI]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 未设置 DEEPSEEK_API_KEY 环境变量")
        print("   获取地址: https://platform.deepseek.com/")
        return None
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE)


def load_papers() -> dict:
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        return {"papers": [], "weekly_topics": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_papers(data: dict):
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        return f"{week_start.month}月{week_start.day}日—{week_end.month}月{week_end.day}日"
    except Exception:
        return week_key


def call_deepseek(client: OpenAI, system_prompt: str, user_message: str, max_tokens: int) -> str:
    """调用 DeepSeek API"""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e)
        if "rate" in error_msg.lower() or "limit" in error_msg.lower():
            print("    ⚠️ API 限速，等待 5 秒...")
            time.sleep(5)
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return response.choices[0].message.content.strip()
            except Exception as e2:
                return f"[失败: {e2}]"
        return f"[失败: {error_msg[:80]}]"


def summarize_paper(client: OpenAI, paper: dict) -> str:
    """总结单篇论文"""
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    if abstract:
        user = f"标题：{title}\n\n摘要：{abstract}"
    else:
        user = f"标题：{title}\n\n（无摘要）"
    return call_deepseek(client, SUMMARY_SYSTEM, user, MAX_TOKENS_SUMMARY)


def generate_weekly_topic(client: OpenAI, titles: list[str]) -> str:
    """生成每周综述标题"""
    if not titles:
        return "本周暂无文献"
    text = "\n".join(f"- {t}" for t in titles[:30])
    return call_deepseek(client, WEEKLY_TOPIC_SYSTEM, f"本周论文标题：\n\n{text}", MAX_TOKENS_TOPIC)


def generate_weekly_keywords(client: OpenAI, titles: list[str]) -> str:
    """提取每周关键词"""
    if not titles:
        return ""
    text = "\n".join(f"- {t}" for t in titles[:30])
    return call_deepseek(client, WEEKLY_KEYWORDS_SYSTEM, f"本周论文标题：\n\n{text}", MAX_TOKENS_KEYWORDS)


def summarize_all_papers(client: OpenAI, papers: list[dict], force_all: bool = False):
    """批量总结论文"""
    unsolved = papers if force_all else [p for p in papers if not p.get("summary_cn", "").strip()]
    if not unsolved:
        print("✅ 所有论文已有中文总结")
        return

    total = len(unsolved)
    print(f"🤖 DeepSeek 中文总结中... ({total} 篇)\n")

    success = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = unsolved[batch_start : batch_start + BATCH_SIZE]
        for i, paper in enumerate(batch):
            idx = batch_start + i + 1
            title_short = paper["title"][:70] + "..." if len(paper["title"]) > 70 else paper["title"]
            print(f"  [{idx}/{total}] {title_short}")

            summary = summarize_paper(client, paper)
            paper["summary_cn"] = summary
            if summary and not summary.startswith("[失败"):
                success += 1
                print(f"    ✅ {summary[:80]}...")
            else:
                print(f"    ❌ {summary}")
            if i < len(batch) - 1:
                time.sleep(0.5)

        save_papers({"papers": papers, "weekly_topics": {}, "last_updated": "", "total_papers": 0, "new_today": 0})
        remaining = total - batch_start - BATCH_SIZE
        if remaining > 0:
            print(f"\n  💾 {min(batch_start + BATCH_SIZE, total)}/{total}，等待{BATCH_DELAY}s...\n")
            time.sleep(BATCH_DELAY)

    print(f"\n✅ 论文总结: {success}/{total}")


def generate_all_weekly_topics(client: OpenAI, papers: list[dict]) -> dict:
    """为所有周生成综述标题和关键词"""
    weeks = defaultdict(list)
    for p in papers:
        wk = get_week_key(p.get("date", ""))
        weeks[wk].append(p["title"])

    topics = {}
    print(f"📅 生成每周综述... ({len(weeks)} 周)\n")
    for wk in sorted(weeks.keys(), reverse=True):
        titles = weeks[wk]
        week_range = get_week_range(wk)
        print(f"  → {wk} ({week_range}) — {len(titles)} 篇")

        topic = generate_weekly_topic(client, titles)
        print(f"    📌 标题: {topic}")

        keywords = generate_weekly_keywords(client, titles)
        print(f"    🏷️ 关键词: {keywords}")

        topics[wk] = {
            "week_key": wk,
            "week_range": week_range,
            "topic": topic,
            "keywords": keywords,
            "paper_count": len(titles),
        }
        time.sleep(0.5)

    return topics


def main():
    force_all = "--all" in sys.argv
    weekly_only = "--weekly" in sys.argv

    client = get_client()
    if not client:
        print("\n💡 DeepSeek API 获取地址: https://platform.deepseek.com/")
        print("   注册后充值 10 元可用数月，非常便宜！")
        sys.exit(1)

    data = load_papers()
    papers = data.get("papers", [])
    if not papers:
        print("📭 没有论文数据，请先运行 fetch_papers.py")
        return

    if force_all:
        for p in papers:
            p["summary_cn"] = ""
        data["weekly_topics"] = {}

    if not weekly_only:
        summarize_all_papers(client, papers, force_all)

    weekly_topics = generate_all_weekly_topics(client, papers)

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
