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

# 提示词：每周深度综述
WEEKLY_ARTICLE_SYSTEM = """你是渔业科学领域的资深学术主编，负责为研究者撰写每周文献综述。

我会提供本周发表的所有渔业相关论文信息（标题、期刊、摘要）。请撰写一篇结构化的中文综述（600-1000字），按以下格式输出：

## 本周研究概览
用一段话（3-4句）概括本周论文的总体情况：共多少篇、主要涉及哪些研究方向、整体研究趋势。

## 高影响力期刊亮点
重点介绍发表在以下高影响力期刊上的研究：Nature, Science, PNAS, Nature Climate Change, Nature Ecology & Evolution, Nature Sustainability, Nature Communications, Science Advances。
对每篇高影响力论文用2-3句话说明其研究内容和意义。如本周无此类论文则写"本周暂无"。

## 创新性研究
挑选3-5篇创新性较强的研究（不限期刊），说明其创新点何在、对本领域的潜在影响。每篇2-3句话。

## 推荐阅读
推荐5篇最值得阅读的论文（考虑期刊影响力、研究创新性、方法新颖性），格式：
1. **论文标题** — 推荐理由（1句话）
2. **论文标题** — 推荐理由（1句话）
...

要求：
- 用专业、流畅的学术中文写作
- 使用中文，但关键术语保留英文
- 实事求是，不夸大
- 标注清楚论文标题以便查找"""

# 旧的简短提示词保留备用
WEEKLY_TOPIC_SYSTEM = """你是渔业科学主编。根据本周论文标题，起一个中文综述标题（10-20字），概括本周研究热点和趋势。只输出标题本身。"""

WEEKLY_KEYWORDS_SYSTEM = """你是渔业科学编辑。从本周论文标题中提取5-8个研究关键词。

要求：
1. 关键词用中文，括号附英文术语
2. 涵盖本周主要研究方向和热点
3. 按重要性排序
4. 每个关键词2-6字
5. 只输出关键词，用逗号分隔，一行输出

示例：种群评估(Stock Assessment), 气候变化(Climate Change), 水产养殖(Aquaculture), MPA保护区, 兼捕减少, 生态系统模型"""


def clean_article(text: str) -> str:
    """清理 AI 生成综述中的客套话前缀"""
    import re
    # 去掉开头的客套话
    prefixes = [
        r"好的，作为渔业科学.*?以下是为您撰写的每周文献综述。\s*",
        r"好的，.*?以下.*?综述[：:]\s*",
        r"以下是.*?综述[：:]\s*",
        r"作为.*?主编.*?撰写的.*?综述[：:]\s*",
    ]
    for pat in prefixes:
        text = re.sub(pat, "", text, flags=re.DOTALL)
    return text.strip()


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


# 高影响力期刊列表
HIGH_IMPACT_JOURNALS = [
    "nature", "science", "pnas",
    "nature climate change", "nature ecology & evolution",
    "nature sustainability", "nature communications", "science advances",
    "proceedings of the national academy",
]


def is_high_impact(journal: str) -> bool:
    """判断是否为高影响力期刊"""
    jl = journal.lower().strip()
    for hj in HIGH_IMPACT_JOURNALS:
        if hj in jl:
            return True
    return False


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
    """生成简短综述标题（用于主页卡片）"""
    if not titles:
        return "本周暂无文献"
    text = "\n".join(f"- {t}" for t in titles[:30])
    return call_deepseek(client, WEEKLY_TOPIC_SYSTEM, f"本周论文标题：\n\n{text}", MAX_TOKENS_TOPIC)


def generate_weekly_article(client: OpenAI, papers: list[dict]) -> str:
    """生成每周深度综述文章"""
    if not papers:
        return "本周暂无文献发表。"

    # 构建论文信息文本
    lines = []
    for i, p in enumerate(papers[:50], 1):  # 最多50篇
        title = p.get("title", "")
        journal = p.get("journal", "")
        abstract = p.get("abstract", "")
        if abstract:
            abstract = abstract[:300]  # 截断过长摘要
        lines.append(f"{i}. 标题：{title}\n   期刊：{journal}\n   摘要：{abstract or '（无摘要）'}")

    papers_text = "\n\n".join(lines)
    user_message = f"以下是本周（{get_week_key(papers[0].get('date', ''))}）发表的渔业相关论文：\n\n{papers_text}"

    return call_deepseek(client, WEEKLY_ARTICLE_SYSTEM, user_message, 2000)


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


def generate_all_weekly_topics(client: OpenAI, papers: list[dict], existing: dict = None) -> dict:
    """为所有周生成综述标题、关键词、深度综述文章、高影响力论文标识
    如果已有深度文章则不重复生成（保留人工确认的好版本）
    """
    weeks = defaultdict(list)
    for p in papers:
        wk = get_week_key(p.get("date", ""))
        weeks[wk].append(p)

    existing = existing or {}
    topics = {}
    print(f"📅 生成每周深度综述... ({len(weeks)} 周)\n")

    for wk in sorted(weeks.keys(), reverse=True):
        week_papers = weeks[wk]
        titles = [p["title"] for p in week_papers]
        week_range = get_week_range(wk)
        hi_count = sum(1 for p in week_papers if is_high_impact(p.get("journal", "")))
        old = existing.get(wk, {})

        print(f"  → {wk} ({week_range}) — {len(week_papers)} 篇 (高影响力: {hi_count})")

        # 简短标题（主页卡片用）——每次都更新
        topic = generate_weekly_topic(client, titles)
        print(f"    📌 标题: {topic}")

        # 深度综述文章 —— 已有的保留不重复生成
        old_article = old.get("article", "") if isinstance(old, dict) else ""
        if old_article and len(old_article) > 200 and not old_article.startswith("[失败"):
            article = old_article
            print(f"    📝 保留已有深度综述 ({len(article)} 字)")
        else:
            print(f"    📝 生成深度综述...")
            article = generate_weekly_article(client, week_papers)
            article = clean_article(article)
            print(f"       ({len(article)} 字)")

        # 关键词 —— 每次都更新
        keywords = generate_weekly_keywords(client, titles)
        print(f"    🏷️ 关键词: {keywords}")

        # 标识高影响力论文
        for p in week_papers:
            p["high_impact"] = is_high_impact(p.get("journal", ""))

        topics[wk] = {
            "week_key": wk,
            "week_range": week_range,
            "topic": topic,
            "keywords": keywords,
            "article": article,
            "paper_count": len(week_papers),
            "high_impact_count": hi_count,
        }
        time.sleep(1)

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

    # 统计需要处理的论文
    unsolved = [p for p in papers if not p.get("summary_cn", "").strip()]
    weeks_with_new = set()
    for p in unsolved:
        weeks_with_new.add(get_week_key(p.get("date", "")))

    if force_all:
        for p in papers:
            p["summary_cn"] = ""
        data["weekly_topics"] = {}
        weeks_with_new = set(get_week_key(p.get("date", "")) for p in papers)

    if not weekly_only:
        if unsolved or force_all:
            summarize_all_papers(client, papers, force_all)
        else:
            print("✅ 所有论文已有中文总结，跳过")

    # 生成/更新每周综述
    old_topics = data.get("weekly_topics", {})
    if weeks_with_new or force_all or weekly_only:
        if weekly_only:
            print("\n📅 --weekly 模式：强制更新所有周综述")
        elif not force_all:
            print(f"\n📅 有新论文的周: {weeks_with_new}")
        weekly_topics = generate_all_weekly_topics(client, papers, old_topics)
    else:
        weekly_topics = old_topics
        print("✅ 本周无新增论文，跳过综述生成")

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
