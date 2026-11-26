#!/usr/bin/env python3
"""
预计算论文向量（语义检索的离线部分）

站点是纯静态的，查询向量要实时算（走 Vercel 代理），但**文档向量可以离线算好**，
存成 int8 量化后的二进制，浏览器 400 KB 就全拿走了，本地做点积即可。

输出：
  docs/data/emb.bin    ← 论文向量矩阵，int8，行优先，每行 dim 维
  docs/data/emb.json   ← 元信息：模型、维度、DOI 顺序

用法：
  python build_embeddings.py            # 增量：只补新论文
  python build_embeddings.py --force    # 全量重算
  python build_embeddings.py --dry-run  # 只看要算多少条

环境变量：EMBED_API_KEY（必填）、EMBED_API_BASE、EMBED_MODEL
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
OUT_DIR = ROOT / "docs" / "data"
BIN_FILE = OUT_DIR / "emb.bin"
META_FILE = OUT_DIR / "emb.json"

EMBED_API_BASE = os.getenv("EMBED_API_BASE", "https://api.siliconflow.cn/v1/embeddings")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")

BATCH = 16
MAX_CHARS = 1200       # 标题 + 标签 + 摘要前段足够表达主题，再长边际收益很低
RETRIES = 3


def doc_text(p: dict) -> str:
    """喂给模型的文本：标题权重最高，补上标签词和摘要开头"""
    tags = []
    for ids in (p.get("tags") or {}).values():
        tags.extend(ids if isinstance(ids, list) else [])
    parts = [p.get("title", ""), " ".join(tags), (p.get("abstract") or "")[:900]]
    return "\n".join(x for x in parts if x)[:MAX_CHARS]


def sig(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def embed_batch(texts: list[str], api_key: str, sess: requests.Session) -> list[list[float]]:
    body = {"model": EMBED_MODEL, "input": texts, "encoding_format": "float"}
    last = ""
    for attempt in range(RETRIES):
        try:
            r = sess.post(EMBED_API_BASE,
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"},
                          json=body, timeout=60)
            if r.status_code == 200:
                data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
                return [d["embedding"] for d in data]
            last = f"HTTP {r.status_code} {r.text[:160]}"
        except requests.RequestException as e:
            last = str(e)[:160]
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"embedding 失败：{last}")


def normalize(vec: list[float]) -> list[float]:
    n = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / n for x in vec]


def to_int8(vec: list[float]) -> bytes:
    """归一化后分量落在 [-1,1]，×127 量化到 int8，误差 < 0.004，余弦相似度几乎无损"""
    return bytes(max(-127, min(127, round(x * 127))) & 0xFF for x in vec)


def load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def main():
    force = "--force" in sys.argv
    dry = "--dry-run" in sys.argv

    if not DATA_FILE.exists():
        print(f"❌ 数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    papers = [p for p in data.get("papers", [])
              if p.get("doi") and not p.get("off_topic") and p.get("title")]

    meta = {} if force else (load_json(META_FILE) or {})
    old_items = {it["doi"]: it for it in meta.get("items", [])}
    dim = meta.get("dim", 0)

    # 旧向量的原始矩阵，用于按行复用
    old_rows = {}
    if old_items and BIN_FILE.exists() and dim:
        raw = BIN_FILE.read_bytes()
        order = meta.get("items", [])
        for i, it in enumerate(order):
            old_rows[it["doi"]] = raw[i * dim:(i + 1) * dim]

    todo = []
    for p in papers:
        txt = doc_text(p)
        s = sig(txt)
        old = old_items.get(p["doi"])
        if old and old.get("sig") == s and p["doi"] in old_rows:
            continue
        todo.append((p, txt, s))

    print(f"📚 论文 {len(papers)} 篇，需向量化 {len(todo)} 篇"
          f"（复用 {len(papers) - len(todo)} 篇）")
    if not todo:
        print("✅ 向量已是最新")
        return
    if dry:
        return

    api_key = os.getenv("EMBED_API_KEY")
    if not api_key:
        # 可选功能：没配 key 就跳过，不让整条流水线变红
        print("⏭️ 未配置 EMBED_API_KEY，跳过语义检索（站点继续用 BM25）")
        print("   配置方法见 VERCEL.md")
        return

    sess = requests.Session()
    new_rows = {}
    print(f"🤖 模型 {EMBED_MODEL} · 每批 {BATCH} 条\n")
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        vecs = embed_batch([t for _, t, _ in chunk], api_key, sess)
        if not dim:
            dim = len(vecs[0])
        for (p, _, s), v in zip(chunk, vecs):
            if len(v) != dim:
                print(f"  ⚠️ 维度不一致，跳过 {p['doi']}")
                continue
            new_rows[p["doi"]] = (s, to_int8(normalize(v)))
        done = min(i + BATCH, len(todo))
        print(f"  [{done}/{len(todo)}] 已算 {len(new_rows)} 篇")
        time.sleep(0.2)

    # 按 papers 顺序拼矩阵；复用旧行，缺的补 0
    order, blobs = [], []
    for p in papers:
        doi = p["doi"]
        if doi in new_rows:
            s, blob = new_rows[doi]
        elif doi in old_rows:
            s, blob = old_items[doi]["sig"], old_rows[doi]
        else:
            s, blob = sig(doc_text(p)), bytes(dim)
        order.append({"doi": doi, "sig": s})
        blobs.append(blob)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    BIN_FILE.write_bytes(b"".join(blobs))
    meta = {
        "model": EMBED_MODEL,
        "dim": dim,
        "count": len(order),
        "quant": "int8/norm*127",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": order,
    }
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"\n✅ {BIN_FILE.relative_to(ROOT)}  {BIN_FILE.stat().st_size / 1024:.0f} KB"
          f" · {len(order)} 篇 × {dim} 维")
    print(f"✅ {META_FILE.relative_to(ROOT)}  {META_FILE.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
