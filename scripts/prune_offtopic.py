#!/usr/bin/env python3
"""
清理与渔业无关的论文

判定逻辑见 tag_papers.assess_relevance()：专业期刊免检，其余论文必须有鱼种标签、
渔业核心主题或正文强渔业词，否则判为无关。

被删的 DOI 记入 data/offtopic.json 黑名单，fetch_papers.py 下次抓取时直接跳过，
避免"删掉又被抓回来"的死循环。

用法：
  python prune_offtopic.py --dry-run   # 只看会删什么
  python prune_offtopic.py             # 真正删除并写黑名单
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tag_papers import tag_paper  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
BLACKLIST_FILE = ROOT / "data" / "offtopic.json"


def load_blacklist() -> list:
    if BLACKLIST_FILE.exists():
        try:
            return json.loads(BLACKLIST_FILE.read_text(encoding="utf-8")).get("dois", [])
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def save_blacklist(dois: list):
    BLACKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    BLACKLIST_FILE.write_text(
        json.dumps({"dois": sorted(set(dois))}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    dry = "--dry-run" in sys.argv
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    papers = data.get("papers", [])

    keep, drop = [], []
    for p in papers:
        # 重新跑一遍打标，确保判定用的是当前规则
        tag_paper(p)
        (drop if p.get("off_topic") else keep).append(p)

    print(f"共 {len(papers)} 篇 → 保留 {len(keep)} / 剔除 {len(drop)}\n")

    if drop:
        print("剔除清单：")
        for p in drop:
            print(f"  · [{p.get('rel_reason','?'):<14}] {p.get('journal','')[:34]:<34} {(p.get('title') or '')[:64]}")
            print(f"    {p.get('doi','')}")

    if dry:
        print(f"\n[dry-run] 未写入。加 --no-dry 参数执行删除。")
        return

    old_bl = load_blacklist()
    new_bl = old_bl + [p["doi"] for p in drop if p.get("doi")]
    save_blacklist(new_bl)

    data["papers"] = keep
    data["total_papers"] = len(keep)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已删除 {len(drop)} 篇，黑名单 {len(old_bl)} → {len(set(new_bl))} 条")


if __name__ == "__main__":
    main()
