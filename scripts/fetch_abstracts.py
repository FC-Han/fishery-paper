#!/usr/bin/env python3
"""
回捞缺失的英文摘要

Crossref 对不少出版商（Springer、Wiley、部分 Elsevier）不返回 abstract，
这些论文此前只能靠标题硬写中文速览，或者干脆空白。
本脚本按 DOI 去 OpenAlex / Semantic Scholar 再要一次摘要，补上后清空旧的中文速览，
让 summarize.py 用真实摘要重新生成。

用法：
  python fetch_abstracts.py              # 补全部缺摘要的
  python fetch_abstracts.py --limit 10   # 只试前 10 篇
  python fetch_abstracts.py --dry-run    # 只看能补到多少，不写文件
"""

import json
import html
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

MAILTO = "fishery-daily@example.com"
USER_AGENT = f"FisheryDailyBot/1.0 (mailto:{MAILTO})"
OPENALEX = "https://api.openalex.org/works/doi:"
S2 = "https://api.semanticscholar.org/graph/v1/paper/DOI:"

MIN_LEN = 80          # 太短的"摘要"多半是 Highlights 或版权声明，宁可不要

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 出版商页面里的摘要在这些 meta 里，按可靠性排序
META_KEYS = ("citation_abstract", "dc.description", "dc.Description",
             "dcterms.description", "og:description", "description")

META_RE = re.compile(r'<meta[^>]+?(?:name|property)\s*=\s*["\']([^"\']+)["\'][^>]*?'
                     r'content\s*=\s*["\']([^"\']*)["\']', re.I | re.S)
LD_RE = re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.){80,})"', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def clean(txt: str) -> str:
    txt = html.unescape(TAG_RE.sub(" ", txt or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    for junk in ("Abstract", "ABSTRACT", "Summary"):
        if txt.startswith(junk):
            txt = txt[len(junk):].lstrip(" :：")
    return txt.strip()


def from_publisher(doi: str, sess: requests.Session) -> Optional[str]:
    """索引库还没收录的新 DOI，直接去出版商落地页读 meta 标签"""
    try:
        r = sess.get("https://doi.org/" + doi, timeout=25, allow_redirects=True,
                     headers={"User-Agent": BROWSER_UA,
                              "Accept-Language": "en-US,en;q=0.9",
                              "Accept": "text/html,application/xhtml+xml"})
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", ""):
            return None
        head = r.text[:400000]
        metas = {k.lower(): v for k, v in META_RE.findall(head)}
        for key in META_KEYS:
            val = metas.get(key)
            if val:
                txt = clean(val)
                if len(txt) >= MIN_LEN:
                    return txt
        m = LD_RE.search(head)
        if m:
            txt = clean(m.group(1).encode().decode("unicode_escape", "ignore"))
            if len(txt) >= MIN_LEN:
                return txt
        return None
    except (requests.RequestException, ValueError):
        return None



def from_openalex(doi: str, sess: requests.Session) -> Optional[str]:
    """OpenAlex 把摘要存成倒排索引 word -> [位置]，需要还原成正文"""
    try:
        r = sess.get(OPENALEX + doi, params={"mailto": MAILTO}, timeout=20)
        if r.status_code != 200:
            return None
        inv = (r.json() or {}).get("abstract_inverted_index")
        if not inv:
            return None
        pos = {}
        for word, idxs in inv.items():
            for i in idxs:
                pos[i] = word
        if not pos:
            return None
        return " ".join(pos[k] for k in sorted(pos)).strip()
    except (requests.RequestException, ValueError):
        return None


def from_s2(doi: str, sess: requests.Session) -> Optional[str]:
    try:
        r = sess.get(S2 + doi, params={"fields": "abstract"}, timeout=20)
        if r.status_code != 200:
            return None
        a = (r.json() or {}).get("abstract")
        return a.strip() if a else None
    except (requests.RequestException, ValueError):
        return None


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


def main():
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (IndexError, ValueError):
            pass
    dry = "--dry-run" in sys.argv

    data = load()
    papers = data.get("papers", [])
    todo = [p for p in papers if not (p.get("abstract") or "").strip() and p.get("doi")]
    if limit:
        todo = todo[:limit]

    if not todo:
        print("✅ 所有论文都已有摘要")
        return

    print(f"📥 待回捞 {len(todo)} 篇（共 {len(papers)} 篇）\n")
    sess = requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})

    stats = {"openalex": 0, "s2": 0, "publisher": 0, "miss": 0}
    for i, p in enumerate(todo, 1):
        doi = p["doi"]
        title = (p.get("title") or "")[:58]
        abs_txt, src = None, "openalex"
        for src, fn in (("openalex", from_openalex), ("s2", from_s2), ("publisher", from_publisher)):
            got = fn(doi, sess)
            if got and len(got) >= MIN_LEN:
                abs_txt = got
                break
        if abs_txt:
            p["abstract"] = abs_txt
            p["abstract_src"] = src
            p["summary_cn"] = ""          # 旧的中文速览是没摘要时写的，作废重生成
            stats[src] += 1
            print(f"  [{i}/{len(todo)}] ✅ {src:<9} {title}")
        else:
            stats["miss"] += 1
            print(f"  [{i}/{len(todo)}] —  {title}")

        if not dry and i % 20 == 0:
            save(data)
            print(f"  💾 已保存 {i}/{len(todo)}\n")
        time.sleep(0.12)                  # OpenAlex 礼貌池 10 req/s

    if not dry:
        save(data)
    total_get = stats["openalex"] + stats["s2"] + stats["publisher"]
    print(f"\n{'[dry-run] ' if dry else ''}补到 {total_get} 篇"
          f"（OpenAlex {stats['openalex']} / S2 {stats['s2']} / 出版商 {stats['publisher']}），"
          f"仍缺 {stats['miss']} 篇")


if __name__ == "__main__":
    main()
