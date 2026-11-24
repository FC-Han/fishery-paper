#!/usr/bin/env python3
"""
DeepSeek 中文摘要脚本

只做一件事：为缺少中文摘要的论文生成 2-4 句中文总结（增量、断点续跑）。
不再生成"每周综述"——站点按日期直接展示每日文献。

用法：
  python summarize.py          # 只补没摘要的
  python summarize.py --all    # 全部重新生成
  python summarize.py --limit 20   # 本次最多处理 20 篇（控制花费）
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

DEEPSEEK_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"
MAX_TOKENS = 320
BATCH_SIZE = 8
BATCH_DELAY = 2
SLEEP_BETWEEN = 0.5

SUMMARY_SYSTEM = """你是渔业科学学术编辑。把英文论文标题与摘要浓缩成中文速览。

要求：
1. 2-4 句话：研究目的 / 方法或数据 / 主要发现或结论，信息密度高
2. 摘要缺失时，仅根据标题写一句客观简介，不要编造数据
3. 面向渔业与水产研究者，术语准确，关键术语可保留英文（如 stock assessment、MPA）
4. 单纯描述现象，不加"本文研究了"这类空话开头，直接说做了什么、发现了什么
5. 只输出正文，不加标题、前缀、序号
6. 明显与渔业水产无关的内容，只输出：非渔业相关"""


def get_client() -> Optional[OpenAI]:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        print("❌ 未设置 DEEPSEEK_API_KEY")
        print("   获取：https://platform.deepseek.com/")
        return None
    return OpenAI(api_key=key, base_url=DEEPSEEK_BASE)


def load() -> dict:
    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save(data: dict):
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def call(client: OpenAI, title: str, abstract: str) -> str:
    user = f"标题：{title}\n\n摘要：{abstract}" if abstract else f"标题：{title}\n\n（出版商未提供摘要）"
    for attempt in range(2):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SUMMARY_SYSTEM},
                          {"role": "user", "content": user}],
                max_tokens=MAX_TOKENS,
                temperature=0.3,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            msg = str(e)
            if attempt == 0 and ("rate" in msg.lower() or "limit" in msg.lower() or "timeout" in msg.lower()):
                print("    ⚠️ 限速/超时，等待 5 秒重试")
                time.sleep(5)
                continue
            return f"[失败: {msg[:80]}]"
    return "[失败: 未知]"


def main():
    force = "--all" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (IndexError, ValueError):
            pass

    data = load()
    papers = data.get("papers", [])
    if not papers:
        print("📭 没有论文数据，请先运行 fetch_papers.py")
        return

    todo = papers if force else [p for p in papers if not (p.get("summary_cn") or "").strip()]
    if limit:
        todo = todo[:limit]

    if not todo:
        print("✅ 所有论文均已有中文摘要")
        return

    client = get_client()
    if not client:
        sys.exit(1)

    total = len(todo)
    print(f"🤖 DeepSeek 摘要生成：{total} 篇\n")
    ok = 0
    for i, p in enumerate(todo, 1):
        t = p.get("title", "")
        print(f"  [{i}/{total}] {t[:68]}{'...' if len(t) > 68 else ''}")
        s = call(client, t, p.get("abstract", ""))
        p["summary_cn"] = s
        if s and not s.startswith("[失败"):
            ok += 1
            print(f"    ✅ {s[:72]}")
        else:
            print(f"    ❌ {s}")

        if i % BATCH_SIZE == 0 or i == total:
            save(data)
            print(f"  💾 已保存 {i}/{total}\n")
            if i < total:
                time.sleep(BATCH_DELAY)
        else:
            time.sleep(SLEEP_BETWEEN)

    save(data)
    print(f"✅ 完成：{ok}/{total} 篇成功")


if __name__ == "__main__":
    main()
