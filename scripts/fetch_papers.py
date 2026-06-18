#!/usr/bin/env python3
"""
渔业文献获取脚本
从 Crossref API 和 Semantic Scholar API 获取每日最新渔业相关论文

搜索策略：
1. 标题精确搜索（query.title）— 确保标题含渔业关键词
2. 特定渔业期刊 ISSN 直接查询 — 获取主流渔业期刊最新论文
3. 后置相关性过滤 — 确保标题或期刊名含渔业相关词汇
"""

import os
import re
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

# API 配置
CROSSREF_BASE = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
USER_AGENT = "FisheryDailyBot/1.0 (mailto:fishery-daily@example.com)"

# === 搜索策略 1: 标题精确搜索 ===
# 这些词必须出现在标题中，确保结果高度相关
TITLE_QUERIES = [
    "fisheries",
    "fish population",
    "fish stock",
    "aquaculture",
    "fish ecology",
    "fish conservation",
    "marine fisheries",
    "fish biology",
    "shellfish aquaculture",
    "fish habitat",
    "bycatch",
    "overfishing",
    "fishery management",
    "fish reproduction",
    "fish disease",
    "fish nutrition",
    "seafood sustainability",
    "marine aquaculture",
    "fish migration",
    "coral reef fisheries",
]

# === 搜索策略 2: 特定渔业期刊 ISSN ===
# 主流渔业/水产/海洋生态期刊
FISHERY_JOURNALS = [
    ("0165-7836", "Fisheries Research"),
    ("1467-2960", "Fish and Fisheries"),
    ("1054-3139", "ICES Journal of Marine Science"),
    ("0706-652X", "Canadian J. Fisheries & Aquatic Sciences"),
    ("0002-8487", "Trans. American Fisheries Society"),
    ("0960-3166", "Reviews in Fish Biology and Fisheries"),
    ("0044-8486", "Aquaculture"),
    ("0022-1112", "Journal of Fish Biology"),
    ("1054-6006", "Fisheries Oceanography"),
    ("0308-597X", "Marine Policy"),
    ("2330-8249", "Reviews in Fisheries Science & Aquaculture"),
    ("0919-9268", "Fisheries Science"),
    ("0165-7836", "Fisheries Research"),
    ("0378-1127", "Forest Ecology and Management"),  # 可能不相关，删掉
    ("0169-5347", "Trends in Ecology & Evolution"),
    ("0171-8630", "Marine Ecology Progress Series"),
    ("0025-326X", "Marine Pollution Bulletin"),
    ("0160-7383", "Annals of Tourism Research"),  # 不相关，删
]

# 更精准的渔业期刊列表（去除非渔业期刊）
FISHERY_JOURNALS = [
    ("0165-7836", "Fisheries Research"),
    ("1467-2960", "Fish and Fisheries"),
    ("1054-3139", "ICES Journal of Marine Science"),
    ("0706-652X", "Canadian J. Fisheries & Aquatic Sciences"),
    ("0002-8487", "Trans. American Fisheries Society"),
    ("0960-3166", "Reviews in Fish Biology and Fisheries"),
    ("0044-8486", "Aquaculture"),
    ("0022-1112", "Journal of Fish Biology"),
    ("1054-6006", "Fisheries Oceanography"),
    ("0308-597X", "Marine Policy"),
    ("2330-8249", "Reviews in Fisheries Science & Aquaculture"),
    ("0919-9268", "Fisheries Science"),
    ("0171-8630", "Marine Ecology Progress Series"),
    ("0025-326X", "Marine Pollution Bulletin"),
    ("0165-7836", "Fisheries Research"),
    ("1365-2419", "Fisheries Oceanography"),
    ("1548-8659", "Trans. American Fisheries Society"),
    ("1444-2906", "Fisheries Science"),
    ("1573-5184", "Reviews in Fish Biology and Fisheries"),
    ("0165-7836", "Fisheries Research"),
]

# 去重 ISSN
_seen = set()
_unique_journals = []
for issn, name in FISHERY_JOURNALS:
    if issn not in _seen:
        _seen.add(issn)
        _unique_journals.append((issn, name))
FISHERY_JOURNALS = _unique_journals

# === 搜索策略 3: 综合期刊（Nature/Science/PNAS 及其子刊） ===
# 这些期刊覆盖广，需要加渔业关键词过滤
COMPREHENSIVE_JOURNALS = [
    ("0028-0836", "Nature"),
    ("0036-8075", "Science"),
    ("0027-8424", "PNAS"),
    ("1758-678X", "Nature Climate Change"),
    ("2397-334X", "Nature Ecology & Evolution"),
    ("2398-9629", "Nature Sustainability"),
    ("2041-1723", "Nature Communications"),
    ("2375-2548", "Science Advances"),
    ("2052-4463", "Scientific Data"),
    ("0028-0836", "Nature"),  # 重复会被去重
]

# 综合期刊搜索使用的渔业关键词
COMP_FISHERY_QUERY = "fisheries fish aquaculture marine overfishing bycatch seafood shellfish"

# 去重综合期刊
_seen2 = set()
_unique_comp = []
for issn, name in COMPREHENSIVE_JOURNALS:
    if issn not in _seen2:
        _seen2.add(issn)
        _unique_comp.append((issn, name))
COMPREHENSIVE_JOURNALS = _unique_comp

# === 相关性过滤关键词 ===
# 标题或期刊名必须包含以下至少一个词，才被视为渔业相关
FISHERY_TERMS = [
    "fish", "fisheries", "fishery", "fishing",
    "aquaculture", "mariculture",
    "shellfish", "crustacean", "mollusc", "mollusk", "bivalve",
    "seafood", "shrimp", "prawn", "oyster", "mussel", "clam", "scallop",
    "crab", "lobster", "abalone", "seaweed", "kelp", "algae",
    "bycatch", "overfishing", "trawl", "trawling", "longline",
    "marine protected area", "marine reserve", "marine conservation",
    "coral reef", "mangrove", "estuar", "seagrass",
    "ocean", "marine", "coastal", "freshwater", "aquatic",
    "stock assessment", "population dynamic",
    "ichthyolog", "elasmobranch", "teleost", "shark", "ray", "tuna",
    "salmon", "cod", "trout", "carp", "tilapia", "catfish",
    "cetacean", "dolphin", "whale", "seal", "sea lion", "otter",
    "ecosystem", "biodiversity", "habitat",
    "plankton", "zooplankton", "phytoplankton", "benth",
    "blue economy", "maritime", "seafarer",
]

# 排除词：标题含这些词大概率不是渔业论文
EXCLUDE_TERMS = [
    "pharmacy", "pharmac", "clinical trial", "diabetes", "cancer",
    "steel column", "concrete", "masonry", "pavement",
    "cryptocurrency", "blockchain", "bitcoin",
    "classroom", "student", "teacher", "curriculum", "pedagog",
    "human resourc", "organizational behavior", "leadership",
    "corporate", "firm perform", "market orientation", "brand",
    "religious", "theolog", "church", "spiritual",
    # 注意不要排除交叉学科论文，如 fishery economics 等
]

# 去重所用的 hash set
SEEN_DOIS = set()


def clean_html(raw: str) -> str:
    """去除 HTML 标签，提取纯文本"""
    if not raw:
        return ""
    return re.sub(r"<[^>]+>", " ", raw).strip()


def clean_abstract(raw: Optional[str]) -> str:
    """清理摘要文本"""
    if not raw:
        return ""
    text = clean_html(raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_authors(authors: Optional[list]) -> str:
    """格式化作者列表为字符串"""
    if not authors:
        return ""
    names = []
    for a in authors:
        given = a.get("given", "")
        family = a.get("family", "")
        if family:
            names.append(f"{family}, {given}" if given else family)
        elif given:
            names.append(given)
    return "; ".join(names[:10])


def is_fishery_relevant(title: str, journal: str, abstract: str = "") -> bool:
    """
    检查论文是否与渔业相关
    要求标题或期刊名包含渔业核心词汇（完整单词匹配），且不包含排除词
    """
    text_lower = f"{title.lower()} {journal.lower()}"

    # 排除检查 — 标题含这些词直接拒绝
    for exclude in EXCLUDE_TERMS:
        if exclude.lower() in title.lower():
            return False

    # 核心渔业词汇 — 必须完整单词匹配
    # 防止 "fish" 匹配到 "selfish", "bassiana" 等
    core_words = [
        "fish", "fishes", "fisheries", "fishery", "fishing", "fisher",
        "aquaculture", "mariculture", "aquafarming",
        "shellfish", "seafood", "shrimp", "prawn", "oyster", "mussel",
        "clam", "scallop", "crab", "lobster", "abalone", "crayfish",
        "seaweed", "kelp", "macroalgae",
        "bycatch", "overfishing", "trawl", "trawling", "longline",
        "ichthyolog", "elasmobranch", "teleost", "fish",
        "cetacean", "dolphin", "porpoise",
    ]

    for word in core_words:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text_lower):
            return True

    # 特定期刊名直接通过（已知渔业/海洋生态期刊）
    fishery_journal_keywords = [
        "marine ecology progress series",
        "marine policy",
        "marine pollution bulletin",
        "ices journal of marine science",
        "fisheries research",
        "fish and fisheries",
        "canadian journal",
        "transactions of the american",
        "reviews in fish",
        "journal of fish",
        "fisheries oceanography",
        "fisheries science",
        "aquaculture",
        "fish physiology",
        "marine biology",
        "frontiers in marine",
    ]
    for jk in fishery_journal_keywords:
        if jk.lower() in journal.lower():
            return True

    return False


# 今天的日期（用于过滤未来论文）
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_date(item: dict) -> str:
    """
    从 Crossref item 中解析出版日期
    优先使用 created（收录日期），避免出版商设定的未来出版日期
    最终日期不会超过今天
    """
    # 优先顺序：created（最可靠的"可获取"日期）→ published-online → published-print
    date_parts_raw = item.get("created") or item.get("published-online") or item.get("published-print")
    date_parts = (date_parts_raw or {}).get("date-parts", [[None]])[0]
    if date_parts and date_parts[0]:
        year = date_parts[0]
        month = date_parts[1] if len(date_parts) > 1 and date_parts[1] else 1
        day = date_parts[2] if len(date_parts) > 2 and date_parts[2] else 1
        pub_date = f"{year:04d}-{month:02d}-{day:02d}"
        # 日期不能超过今天（出版商可能预设未来日期）
        if pub_date > TODAY:
            # 回退到 created 日期
            created_raw = item.get("created") or item.get("deposited")
            created_parts = (created_raw or {}).get("date-parts", [[None]])[0]
            if created_parts and created_parts[0]:
                cy = created_parts[0]
                cm = created_parts[1] if len(created_parts) > 1 and created_parts[1] else 1
                cd = created_parts[2] if len(created_parts) > 2 and created_parts[2] else 1
                pub_date = f"{cy:04d}-{cm:02d}-{cd:02d}"
            if pub_date > TODAY:
                pub_date = TODAY
        return pub_date
    return ""


def make_paper(item: dict, source: str, keyword: str) -> Optional[dict]:
    """从 API 响应构建论文字典，包含相关性过滤"""
    doi = item.get("DOI", "")
    if not doi or doi in SEEN_DOIS:
        return None

    title = item.get("title", [""])[0] if item.get("title") else ""
    if not title:
        return None

    abstract = clean_abstract(item.get("abstract"))
    authors = parse_authors(item.get("author"))
    journal = item.get("container-title", [""])[0] if item.get("container-title") else ""
    pub_date = parse_date(item)

    # 相关性过滤（仅对标题搜索和 S2 搜索启用，ISSN 期刊搜索不需要）
    if source in ("crossref", "semantic_scholar") and not is_fishery_relevant(title, journal, abstract):
        return None

    SEEN_DOIS.add(doi)

    return {
        "doi": doi,
        "title": title.strip(),
        "authors": authors,
        "journal": journal,
        "date": pub_date,
        "abstract": abstract,
        "summary_cn": "",
        "url": f"https://doi.org/{doi}",
        "source": source,
        "keywords_matched": keyword,
    }


def fetch_crossref_by_title(query: str, from_date: str, until_date: str, rows: int = 10) -> list[dict]:
    """策略 1: 用标题精确搜索 (query.title)"""
    params = {
        "query.title": query,
        "filter": f"type:journal-article,from-pub-date:{from_date},until-pub-date:{until_date}",
        "rows": rows,
        "sort": "published",
        "order": "desc",
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(CROSSREF_BASE, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [Crossref Title] '{query}' 失败: {e}")
        return []

    papers = []
    for item in data.get("message", {}).get("items", []):
        paper = make_paper(item, "crossref", query)
        if paper:
            papers.append(paper)

    return papers


def fetch_crossref_by_issn(issn: str, journal_name: str, from_date: str, until_date: str, rows: int = 20) -> list[dict]:
    """策略 2: 按期刊 ISSN 直接查询最新论文"""
    params = {
        "filter": f"type:journal-article,issn:{issn},from-pub-date:{from_date},until-pub-date:{until_date}",
        "rows": rows,
        "sort": "published",
        "order": "desc",
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(CROSSREF_BASE, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [ISSN] {journal_name} ({issn}) 失败: {e}")
        return []

    papers = []
    for item in data.get("message", {}).get("items", []):
        doi = item.get("DOI", "")
        if not doi or doi in SEEN_DOIS:
            continue

        title = item.get("title", [""])[0] if item.get("title") else ""
        if not title:
            continue

        SEEN_DOIS.add(doi)

        abstract = clean_abstract(item.get("abstract"))
        authors = parse_authors(item.get("author"))

        papers.append({
            "doi": doi,
            "title": title.strip(),
            "authors": authors,
            "journal": journal_name,
            "date": parse_date(item),
            "abstract": abstract,
            "summary_cn": "",
            "url": f"https://doi.org/{doi}",
            "source": "crossref_issn",
            "keywords_matched": journal_name,
        })

    return papers


def fetch_semantic_scholar(query: str, from_date: str, until_date: str, limit: int = 10) -> list[dict]:
    """策略 3: 从 Semantic Scholar API 获取论文（补充）"""
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,abstract,authors,journal,publicationDate,externalIds,url,tldr",
    }
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        resp = requests.get(SEMANTIC_SCHOLAR_BASE, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [SemanticScholar] '{query}' 失败: {e}")
        return []

    papers = []
    for item in data.get("data", []):
        doi = (item.get("externalIds") or {}).get("DOI", "")
        if not doi or doi in SEEN_DOIS:
            continue

        title = item.get("title", "")
        if not title:
            continue

        journal_info = item.get("journal") or {}
        journal = journal_info.get("name", "")

        # 相关性过滤
        if not is_fishery_relevant(title, journal):
            continue

        SEEN_DOIS.add(doi)

        abstract = item.get("abstract", "") or ""
        tldr = (item.get("tldr") or {}).get("text", "")
        authors_list = item.get("authors", [])
        authors = "; ".join(a.get("name", "") for a in authors_list[:10])

        papers.append({
            "doi": doi,
            "title": title.strip(),
            "authors": authors,
            "journal": journal,
            "date": item.get("publicationDate", ""),
            "abstract": abstract or tldr,
            "summary_cn": "",
            "url": f"https://doi.org/{doi}",
            "source": "semantic_scholar",
            "keywords_matched": query,
        })

    return papers


def fetch_comprehensive_journal(issn: str, journal_name: str, from_date: str, until_date: str, rows: int = 10) -> list[dict]:
    """策略 3: 搜索综合期刊中与渔业相关的论文"""
    params = {
        "query": COMP_FISHERY_QUERY,
        "filter": f"type:journal-article,issn:{issn},from-pub-date:{from_date},until-pub-date:{until_date}",
        "rows": rows,
        "sort": "published",
        "order": "desc",
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(CROSSREF_BASE, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [综合期刊] {journal_name} ({issn}) 失败: {e}")
        return []

    papers = []
    for item in data.get("message", {}).get("items", []):
        paper = make_paper(item, "crossref", journal_name)
        if paper:
            papers.append(paper)

    return papers


def load_existing_papers() -> dict:
    """加载已有的论文数据"""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return {"last_updated": "", "papers": []}


def save_papers(data: dict):
    """保存论文数据到 JSON 文件"""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def prune_old_papers(papers: list[dict], days: int = 14) -> list[dict]:
    """删除超过指定天数的旧论文"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    return [p for p in papers if p.get("date", "") >= cutoff]


def main():
    """主函数"""
    # 日期范围
    is_ci = os.getenv("CI", "").lower() == "true" or os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    if is_ci:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        from_date = yesterday
        until_date = yesterday
        print(f"🔍 CI 模式：获取 {from_date} 的论文")
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        from_date = week_ago
        until_date = today
        print(f"🧪 本地模式：获取 {from_date} 到 {until_date} 的论文")

    # 加载已有数据
    existing = load_existing_papers()
    existing_dois = {p["doi"] for p in existing.get("papers", []) if p.get("doi")}
    global SEEN_DOIS
    SEEN_DOIS = existing_dois.copy()

    all_new_papers = []

    # 策略 1: 标题精确搜索
    print("\n📚 策略 1: 标题精确搜索...")
    for query in TITLE_QUERIES:
        print(f"  → title:'{query}'")
        papers = fetch_crossref_by_title(query, from_date, until_date)
        all_new_papers.extend(papers)
        print(f"    ✅ {len(papers)} 篇")
        time.sleep(0.3)

    # 策略 2: 特定期刊 ISSN 搜索
    print(f"\n📚 策略 2: {len(FISHERY_JOURNALS)} 本渔业期刊 ISSN 搜索...")
    for issn, name in FISHERY_JOURNALS:
        print(f"  → {name} ({issn})")
        papers = fetch_crossref_by_issn(issn, name, from_date, until_date)
        all_new_papers.extend(papers)
        print(f"    ✅ {len(papers)} 篇")
        time.sleep(0.3)

    # 策略 3: 综合期刊搜索
    print(f"\n📚 策略 3: {len(COMPREHENSIVE_JOURNALS)} 本综合期刊搜索（Nature/Science/PNAS等）...")
    for issn, name in COMPREHENSIVE_JOURNALS:
        print(f"  → {name} ({issn})")
        papers = fetch_comprehensive_journal(issn, name, from_date, until_date)
        all_new_papers.extend(papers)
        print(f"    ✅ {len(papers)} 篇渔业相关")
        time.sleep(0.3)

    # 策略 4: Semantic Scholar 补充
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        print("\n📖 策略 3: Semantic Scholar 补充搜索...")
        s2_queries = ["fisheries", "aquaculture", "marine ecology", "fish conservation", "fish biology"]
        for query in s2_queries:
            print(f"  → '{query}'")
            papers = fetch_semantic_scholar(query, from_date, until_date)
            all_new_papers.extend(papers)
            print(f"    ✅ {len(papers)} 篇")
            time.sleep(1.0)

    # 合并新旧论文
    all_papers = existing.get("papers", []) + all_new_papers
    all_papers.sort(key=lambda x: x.get("date", ""), reverse=True)
    all_papers = prune_old_papers(all_papers)

    # 保存
    data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_papers": len(all_papers),
        "new_today": len(all_new_papers),
        "papers": all_papers,
    }
    save_papers(data)

    print(f"\n{'='*50}")
    print(f"✅ 完成！总计 {len(all_papers)} 篇论文，本次新增 {len(all_new_papers)} 篇")
    print(f"   数据保存在: {DATA_FILE}")

    if all_new_papers:
        print(f"\n📋 新增论文概览（前 15 篇）：")
        for paper in all_new_papers[:15]:
            title = paper["title"][:90] + "..." if len(paper["title"]) > 90 else paper["title"]
            print(f"   • [{paper['date']}] [{paper['journal'][:30]}] {title}")
        if len(all_new_papers) > 15:
            print(f"   ... 还有 {len(all_new_papers) - 15} 篇")


if __name__ == "__main__":
    main()
