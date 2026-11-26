#!/usr/bin/env python3
"""
论文关联计算（离线，零 API 成本）

对每篇论文计算 top-K 篇最相关论文，用于「相关文献」推荐与关系图。
相关性 = 文本语义相似度（TF-IDF 余弦） + 标签重叠（分维度加权 Jaccard）

用法：
  python build_relations.py            # 增量：只算缺失的
  python build_relations.py --force    # 全量重算

输出写入 data/papers.json 每篇的 rel 字段：
  [{"d": "10.xxx", "s": 0.42, "t": ["黄海", "声学遥测"]}]
"""

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"

TOP_K = 4
MIN_SCORE = 0.13          # 低于此分不推荐，避免硬凑
TEXT_WEIGHT = 0.45
TAG_WEIGHT = 0.50
JOURNAL_BONUS = 0.05

# bigram TF-IDF 余弦的绝对尺度很小（全体中位 0.012、p99 仅 0.075），
# 直接加权会被压成噪声，需按参考值归一化放大后再参与融合。
# 参考值取 0.15（约 p99.9）而非 0.06（约 p98），否则最相关的那批会全部撞到 1.0，
# 分数被压平、失去区分度
TEXT_REF = 0.15
ABS_LIMIT = 700           # 摘要只取前 N 字符，防止长摘要主导
TITLE_BOOST = 3

# 中文双字切分时，含这些虚字的 bigram 直接丢弃
STOP_CHARS = set("的了在是和与及对为中冇之也等被从而或其本该这不无未可能会将把以于上下内外时又并很更最较都就还只再已曾由向给让使所者着过个些吗呢吧啊")

EN_STOP = set("""
a an the and or of in on at to for with from by as is are was were be been being
this that these those it its their there here we our they them which who whom whose
than then thus also both each other such more most less least can could may might
not no nor but if while where when how what all any some only very much many
study studies result results paper article present presents show shows shown
using used use based approach method methods analysis data however although
""".split())

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
LATIN_WORD = re.compile(r"[a-z][a-z\-]{2,}")


def tokenize(text: str) -> list[str]:
    """英文按词、中文按 bigram；丢弃含虚字的中文 bigram"""
    if not text:
        return []
    t = text.lower()
    out = []
    for w in LATIN_WORD.findall(t):
        if w not in EN_STOP:
            out.append(w)
    for run in CJK_RUN.findall(t):
        n = len(run)
        if n == 1:
            out.append(run)
        else:
            for i in range(n - 1):
                bg = run[i:i + 2]
                if not (STOP_CHARS & set(bg)):
                    out.append(bg)
    return out


def doc_tokens(p: dict) -> list[str]:
    """组合标题、摘要、中文速览；标题加权"""
    title = tokenize(p.get("title", ""))
    body = tokenize((p.get("abstract") or "")[:ABS_LIMIT])
    cn = p.get("summary_cn") or ""
    if cn.startswith("[") or "非渔业相关" in cn:
        cn = ""
    body += tokenize(cn)
    return title * TITLE_BOOST + body


def build_tfidf(token_lists: list[list[str]]):
    """返回每篇的 L2 归一化 tfidf 稀疏向量 [{token: weight}]"""
    n = len(token_lists)
    df = Counter()
    for toks in token_lists:
        df.update(set(toks))

    vectors = []
    for toks in token_lists:
        tf = Counter(toks)
        vec = {}
        for tok, cnt in tf.items():
            if cnt < 1:
                continue
            idf = math.log((n + 1) / (df[tok] + 1)) + 1.0
            w = (1.0 + math.log(cnt)) * idf
            if w > 0:
                vec[tok] = w
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({k: v / norm for k, v in vec.items()})
    return vectors


def cosine(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


# 共有标签按个数加分（而非 Jaccard）：共享 1 个鱼种本身就是强语义信号，
# 不该因为两篇各自标签多就被并集除小。同维度第 2 个共有标签权重减半。
DIM_BONUS = {
    "species": (0.26, 0.13),
    "region": (0.22, 0.11),
    "method": (0.20, 0.10),
    "theme": (0.10, 0.05),
}


def tag_similarity(ta: dict, tb: dict) -> tuple[float, list[str]]:
    """共有标签加分制；同时返回共有的非主题标签（用于图上标边）"""
    score = 0.0
    shared = []
    for dim, bonuses in DIM_BONUS.items():
        sa = set(ta.get(dim) or [])
        sb = set(tb.get(dim) or [])
        if dim == "theme":
            sa.discard("misc")
            sb.discard("misc")
        inter = sa & sb
        if not inter:
            continue
        for k, b in enumerate(bonuses):
            if k < len(inter):
                score += b
        if dim != "theme":
            shared.extend(sorted(inter))
    return min(score, 1.0), shared


def main():
    force = "--force" in sys.argv

    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    papers = data.get("papers", [])

    # 只对可展示论文建关联（与站点口径一致）
    idx = [i for i, p in enumerate(papers)
           if p.get("doi") and p.get("title") and p.get("date") and not p.get("off_topic")]

    if len(idx) < 2:
        print("⚠️ 可展示论文不足 2 篇，跳过关联计算")
        return

    # 增量：已算过的跳过（--force 时全算）
    if not force:
        need = [i for i in idx if not papers[i].get("rel")]
        if not need:
            print(f"✅ 全部 {len(idx)} 篇均已有关系数据，跳过（用 --force 重算）")
            return
    else:
        need = idx

    print(f"🔗 计算论文关联：{len(idx)} 篇候选，待算 {len(need)} 篇")

    # 词表 → 向量（要对全部候选建，检索时才完整）
    token_lists = [doc_tokens(papers[i]) for i in idx]
    vectors = build_tfidf(token_lists)

    # id → 中文名
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from tag_papers import lexicon  # type: ignore
        zh_of = {(t["dim"], t["id"]): t["zh"] for t in lexicon()}
    except Exception:
        zh_of = {}

    pos_of = {paper_i: pos for pos, paper_i in enumerate(idx)}
    need_pos = {pos_of[i] for i in need}

    total_edges = 0
    for pos in range(len(idx)):
        if pos not in need_pos:
            continue
        pi = idx[pos]
        a_vec = vectors[pos]
        a_tags = papers[pi].get("tags") or {}

        scored = []
        for qpos in range(len(idx)):
            if qpos == pos:
                continue
            qi = idx[qpos]
            # 跳过标题完全相同（同一论文不同来源）
            if papers[qi].get("title", "").strip().lower() == papers[pi].get("title", "").strip().lower():
                continue

            cos = min(1.0, cosine(a_vec, vectors[qpos]) / TEXT_REF)
            tsim, shared_ids = tag_similarity(a_tags, papers[qi].get("tags") or {})
            same_j = (papers[qi].get("journal") or "").strip().lower() == \
                     (papers[pi].get("journal") or "").strip().lower()
            score = TEXT_WEIGHT * cos + TAG_WEIGHT * tsim + (JOURNAL_BONUS if same_j else 0.0)
            if score >= MIN_SCORE:
                scored.append((score, qi, shared_ids))

        scored.sort(key=lambda x: -x[0])
        top = scored[:TOP_K]

        rel = []
        for score, qi, shared_ids in top:
            # 优先用非主题标签做边标注，最多 2 个
            names = [zh_of.get((d, tid), tid)
                     for d in ("species", "region", "method")
                     for tid in (papers[pi].get("tags", {}).get(d) or [])
                     if tid in shared_ids]
            if not names:
                # 没有共有的实体标签，退回共有的研究主题，避免页面上只剩一个光秃秃的百分比
                th_a = set(a_tags.get("theme") or []) - {"misc"}
                th_b = set(papers[qi].get("tags", {}).get("theme") or []) - {"misc"}
                names = [zh_of.get(("theme", t), t) for t in sorted(th_a & th_b)]
            # 去重保序
            seen = set()
            uniq = []
            for nm in names:
                if nm not in seen:
                    seen.add(nm)
                    uniq.append(nm)
            rel.append({
                "d": papers[qi]["doi"],
                "s": round(score, 3),
                "t": uniq[:2],
            })

        papers[pi]["rel"] = rel
        total_edges += len(rel)

    # 统计
    with_rel = sum(1 for i in idx if papers[i].get("rel"))
    no_rel = [papers[i].get("title", "")[:60] for i in idx if not papers[i].get("rel")]
    avg = total_edges / max(1, with_rel)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"✅ 完成：{with_rel}/{len(idx)} 篇有关联，共 {total_edges} 条边，平均 {avg:.1f} 条/篇")
    if no_rel:
        print(f"⚠️ {len(no_rel)} 篇无关联（孤立节点，多为无摘要的短记录）")
        for t in no_rel[:5]:
            print(f"   · {t}")


if __name__ == "__main__":
    main()
