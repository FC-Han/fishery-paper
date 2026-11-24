# 🐟 渔业文献速览

> Fisheries Science Daily Digest — 每日自动抓取 · DeepSeek 中文摘要 · 四维标签检索

[![Daily Update](https://github.com/FC-Han/fishery-paper/actions/workflows/daily-update.yml/badge.svg)](https://github.com/FC-Han/fishery-paper/actions/workflows/daily-update.yml)

在线浏览：**https://fc-han.github.io/fishery-paper/**

---

## ✨ 做了什么

| 能力 | 说明 |
|------|------|
| 🔍 双通道抓取 | 标题关键词搜索 + 27 本渔业/水产/海洋期刊 ISSN 直查，另可接 Semantic Scholar 补充 |
| 🤖 中文速览 | DeepSeek 为每篇论文生成 2–4 句中文摘要，术语保留英文 |
| 🏷️ 四维标签 | **研究主题 / 研究鱼种 / 海域区域 / 方法手段**，69 种标签，规则引擎自动标注 |
| 🎛️ 标签筛选 | 点任意标签即筛选，同维度取并集、跨维度取交集；标签旁显示实时命中数 |
| 📅 按日展示 | 不再做"每周综述"，直接按日期倒序展示每日文献，每天的热点主题一眼可见 |
| ⚡ 单文件站点 | 数据内联进 `index.html`，双击即可打开；英文摘要按需懒加载 |
| 🌗 体验 | 暗色模式、移动端抽屉式筛选、`/` 快捷搜索、`Esc` 关闭 |

## 🖼 页面结构

```
docs/
├── index.html            ← 全部页面（数据内联，约 300 KB）
└── data/
    ├── abstracts.json    ← 英文摘要，点"英文摘要"时才请求
    └── papers.json       ← 完整结构化数据，可当 API 用
```

## 🏷 标签体系

四个维度互不干扰，一篇论文每维最多保留 2–4 个标签：

| 维度 | 标签数 | 例子 |
|------|--------|------|
| 研究主题 | 15 | 种群评估与管理、水产养殖、生态与栖息地、气候变化与环境、病害与免疫、遗传与基因组、加工品质与食品… |
| 研究鱼种 | 19 | 鲑鳟类、鳕类、鲤科、黄鱼与石首鱼、虾类、贝类、藻类、鲨鳐类、鲸豚… |
| 海域区域 | 14 | 渤海/黄海/东海/南海、北太平洋、北大西洋、地中海、南美海域、极地、淡水与湖泊… |
| 方法手段 | 11 | 环境DNA、稳定同位素、耳石与硬组织、声学遥测、遥感、机器学习、分布模型、统计建模… |

**标注逻辑**（`scripts/tag_papers.py`）：

- 纯规则 + 词典，**零 API 成本**、结果稳定可复现
- 标题命中权重 ×3，摘要命中 ×1（同一关键词摘要内最多计 3 次）
- 各维度阈值不同：主题/鱼种需更强证据（3 分），海域/方法单次命中即可（2 分）
- 顺带标记 `is_review`（综述）、`high_impact`（高影响期刊）、`off_topic`（医学病例、材料工程等无关文献，站点自动隐藏）

想加标签直接改 `RULES` 列表即可，`T()/S()/G()/M()` 分别是四个维度的构造函数，`!word` 表示整词匹配、`word` 表示子串匹配：

```python
T("aqua", "水产养殖", "Aquaculture", ["aquaculture", "mariculture", "!ras!"]),
```

改完跑 `python scripts/tag_papers.py --force` 重新标注。

## 🚀 本地运行

```bash
git clone git@github.com:FC-Han/fishery-paper.git
cd fishery-paper
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY

python scripts/fetch_papers.py     # 1. 抓论文（无需 key）
python scripts/summarize.py        # 2. 中文摘要（需 key，增量）
python scripts/tag_papers.py       # 3. 自动打标（无需 key）
python scripts/generate_site.py    # 4. 生成站点

open docs/index.html               # 或：cd docs && python -m http.server 8000
```

常用参数：

```bash
python scripts/fetch_papers.py            # 本地模式默认回看 7 天
python scripts/summarize.py --limit 20    # 本次只处理 20 篇，控制花费
python scripts/tag_papers.py --force      # 改词库后全量重标
```

## 📦 部署

1. **Secret**：`Settings → Secrets and variables → Actions` 添加 `DEEPSEEK_API_KEY`
2. **Pages**：`Settings → Pages` → Source 选 `Deploy from a branch`，分支 `main`、目录 `/docs`
3. **自动运行**：每天北京时间 16:00 抓取（回看 5 天，靠 DOI 去重，避免索引延迟漏文）

要在本地/服务器跑定时任务，把上面四条命令串起来即可。

## 💰 成本

| 项目 | 开销 |
|------|------|
| Crossref / Semantic Scholar | 免费 |
| GitHub Actions | 免费 |
| DeepSeek（约 20 篇/天） | ≈ ¥0.03/天，¥1/月 |

## 📊 文献来源

**渔业与水产期刊（27 本）**：Fisheries Research · Fish and Fisheries · ICES JMS · CJFAS · TAFS · North American JFM · Reviews in Fish Biology and Fisheries · Reviews in Fisheries Science & Aquaculture · Fisheries Management and Ecology · Fisheries Oceanography · Fisheries Science · Aquaculture · Aquaculture Reports · Aquaculture International · Aquaculture Research · Reviews in Aquaculture · Journal of Fish Biology · Journal of Fish Diseases · Ecology of Freshwater Fish · Journal of Applied Ichthyology · Fishes · MEPS · Marine Policy · Marine Pollution Bulletin · Frontiers in Marine Science · Hydrobiologia · ECSS

**综合期刊**：Nature · Science · PNAS · Nature Climate Change · Nature Ecology & Evolution · Nature Sustainability · Nature Communications · Science Advances · Scientific Data

## 📝 License

MIT
