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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "docs"
DATA_OUT = OUTPUT_DIR / "data"

RETENTION_DAYS = 120
BJT = timezone(timedelta(hours=8))


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
        "is_review": bool(p.get("is_review")),
        "high_impact": bool(p.get("high_impact")),
    }


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

    print(f"\n📊 {len(papers)} 篇 · {len(dates)} 天 · {len(journals)} 本期刊 · {tag_kinds} 种标签")


if __name__ == "__main__":
    main()
