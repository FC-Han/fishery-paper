# 🐟 渔业文献速览

> Fisheries Science Daily Digest — 每日自动抓取 · DeepSeek 中文摘要 · 四维标签检索

[![Daily Update](https://github.com/FC-Han/fishery-paper/actions/workflows/daily-update.yml/badge.svg)](https://github.com/FC-Han/fishery-paper/actions/workflows/daily-update.yml)

在线浏览：**https://fc-han.github.io/fishery-paper/**

---

## ✨ 做了什么

| 能力 | 说明 |
|------|------|
| 🔍 双通道抓取 | 标题关键词搜索 + 27 本渔业/水产/海洋期刊 ISSN 直查，另可接 Semantic Scholar 补充 |
| 📥 摘要回捞 | Crossref 不给摘要的新论文，按 DOI 从 OpenAlex → Semantic Scholar → 出版商页面三级回捞 |
| 🤖 中文速览 | DeepSeek 为每篇论文生成 2–4 句中文摘要，术语保留英文 |
| 🏷️ 四维标签 | **研究主题 / 研究鱼种 / 海域区域 / 方法手段**，69 种标签，规则引擎自动标注 |
| 🎛️ 标签筛选 | 点任意标签即筛选，同维度取并集、跨维度取交集；标签旁显示实时命中数 |
| 📅 按日展示 | 不再做"每周综述"，直接按日期倒序展示每日文献，每天的热点主题一眼可见 |
| 🔗 论文关联 | 每篇论文自动关联 4 篇最相关文献（文本相似 + 标签重叠），点开可看关系图并逐级探索 |
| 🔎 站内检索 | BM25 全文检索（标题/摘要/标签/期刊/作者），按相关度排序 + 关键词高亮，支持 `?q=` 分享链接 |
| 🧠 语义检索 | 可选：向量余弦 + BM25 混合排序，换个说法也能搜到；未配置时自动退回纯 BM25 |
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

## 🔗 论文关联

点卡片底部的「相关 N」展开推荐列表，点「关系图」进入可探索的关系网络：中心是当前论文，
四周是关联最紧的文献，点任意节点即以它为中心继续走，支持返回上一级。

**算法**（`scripts/build_relations.py`，纯离线、零 API 成本，344 篇约 2 秒）：

- 文本相似：标题（权重 ×3）+ 英文摘要前 700 字符 + 中文速览，中英文分别按 bigram / 单词切分后做 TF-IDF 余弦
- 标签重叠：按共有的标签**个数**加分（同维度第 2 个减半），而非 Jaccard —— 共享 1 个鱼种本身就是强信号，不该被并集除小
- 融合：`0.45 × 文本 + 0.50 × 标签 + 0.05 × 同期刊`
- bigram TF-IDF 的绝对尺度很小（全体中位 0.012），所以文本分先按参考值 0.06 归一化再参与融合，否则会被压成噪声

结果写回 `data/papers.json` 的 `rel` 字段，生成站点时转成数组下标内联，344 篇 × 4 条约 40 KB。
每天 CI 里全量重算（比增量更正确：新论文也要能出现在旧论文的关联里）。

## 📥 摘要回捞

Crossref 对 Springer / Wiley / Elsevier 等不少出版商**不返回 abstract**，这些论文只有标题：
中文速览写不出来，BM25 检索也基本搜不到。所以入库后再按 DOI 要一次，三级依次尝试：

| 级别 | 来源 | 说明 |
|------|------|------|
| 1 | OpenAlex | `abstract_inverted_index` 是倒排索引（词 → 位置），需还原成正文 |
| 2 | Semantic Scholar | `fields=abstract`，覆盖略差但能捡漏 |
| 3 | 出版商落地页 | 跟随 `doi.org` 跳转，读 `citation_abstract` / `dc.description` meta |

刚落库的新 DOI 两个索引库常常都还没收录（实测 2026-11 的 DOI 在 OpenAlex 全是 404），
这时第三级才是主力。实测 100 篇缺摘要：OpenAlex 44 篇 + 出版商 50 篇，仍缺 6 篇
（Wiley、Taylor & Francis 有 Cloudflare 拦截，只能等索引库收录）。

补到摘要后会**清空该篇的旧中文速览**——那是没摘要时硬写的，得让 `summarize.py` 用真摘要重来。
脚本每天都跑，索引库追上来自动补上，不需要人工干预。

## 🎯 相关性过滤

Crossref 的 ISSN 抓取拿的是整本期刊，而 `Frontiers in Marine Science`、`Marine Policy` 这类刊
什么都发——航运排放法规、海堤越浪、混凝土渗透性、甚至"C 刊"的人力资源论文都会混进来。
光靠"标题里出现 fish 就留"会把《误吞鱼刺致胃穿孔》也当成渔业文献。

所以判定改成**正向证据制**（`scripts/tag_papers.py` 的 `assess_relevance()`），按优先级依次过：

| 顺序 | 判据 | 结果 |
|---|---|---|
| 1 | 渔业/水产专业期刊（`Fish and Fisheries`、`Aquaculture`、`Fishes` …） | ✅ 免检 |
| 2 | 医学/临床类期刊（`Cureus`、`Diagnostic*`、`*Allergolog*` …） | ❌ 直接排除 |
| 3 | 领域标志词：航运、港口、海工、混凝土、HRM、昆虫（`OFF_TOPIC_STRICT`） | ❌ 直接排除 |
| 4 | 标题是仿生机器人研究（`robotic fish`、`underactuated`） | ❌ 直接排除 |
| 5 | 命中鱼种标签（黄鱼、鲑鳟、虾蟹贝…） | ✅ 保留 |
| 6 | 命中渔业核心主题（水产养殖 / 种群评估与管理） | ✅ 保留 |
| 7 | 临床、材料、食品包装、法律人文类词（`OFF_TOPIC_SOFT`） | ❌ 排除 |
| 8 | 标题点到水生生物，或正文出现 ≥2 次 | ✅ 保留 |
| 9 | 其余 | ❌ 排除 |

三条设计取舍值得说：

- **黑名单分两级**。`concrete`、`surgical`、`tumor`、`packaging` 这类词在真渔业论文里也会出现
  （"earthen and concrete ponds"、"surgical implantation of acoustic transmitters"、"鱼明胶膜"），
  所以只在鱼种/主题等正向证据都不成立时才拿来定罪；而航运、海工、HRM 这些在渔业论文里
  基本不可能出现的词，直接前置硬拦。
- **机器人只在标题上判**。飞鱼滑翔的论文摘要在讨论应用时会写 "biomimetic robots"，
  但标题绝不会是机器人研究。
- **人文/法律词放软层**。渔业法、渔业史的论文能过（有 `stock` 主题），
  纯法学的《论鱼射击机赌博的法律责任》过不了。

清理由 `scripts/prune_offtopic.py` 执行：把判定无关的论文从数据集移除，DOI 写进
`data/offtopic.json`；`fetch_papers.py` 每次抓取先读这个黑名单并跳过，所以**删掉的不再被抓回来**。
每日 CI 在打标之后自动跑一遍，新混进来的噪声当天就被清掉。

## 🔎 站内检索（BM25）

纯前端的轻量检索引擎，打开页面即在浏览器里建好索引：**零后端、零 API 成本**，344 篇的建索引 + 单次查询都在 10 ms 内。

- **分词**：中文不依赖词典，CJK 连续段切 bigram（"大黄鱼" → 大黄 / 黄鱼），英文按词，中英混排自动分开
- **字段加权**：标题 ×3.2、标签 ×2.2、期刊 ×1.8、摘要 ×1.0、作者 ×0.7，`k1=1.35`、`b=0.72` 做长度归一
- **多词查询**：先要求全部词项命中；查不到时按 IDF **从低区分度往高逐个丢词**，而不是一把退化成 OR。
  例如「大黄鱼 养殖」会守住"大黄+黄鱼"这个高区分度组合，只返回真正的黄鱼养殖文献
- **单字回退**：中文单字（如"鱼"）直扫原文，避免 bigram 索引漏召回
- **结果呈现**：按相关度排序，命中词在标题与摘要里高亮；关键词以标签形式显示在结果条上
- **可分享**：`.../index.html?q=大黄鱼` 直接打开就带着搜索结果

页面上按 `/` 可快速聚焦搜索框。

## 🧠 语义检索（可选）

BM25 只认字面，换个说法就搜不到了（"鱼的耳石" vs `otolith`）。语义检索补这一块：

- **文档向量离线算**：`scripts/build_embeddings.py` 把标题 + 标签 + 摘要前段喂给 embedding 模型，
  L2 归一化后 int8 量化存成 `docs/data/emb.bin`，344 篇约 350 KB，浏览器打开搜索时再取
- **查询向量实时算**：走 Vercel 上的 `api/embed.js` 代理，key 留在服务端，前端只认代理地址
- **混合排序**：`0.55 × BM25 归一 + 0.45 × 余弦`；BM25 一篇都没命中时，余弦 ≥ 0.34 的候选会补进来
- **优雅降级**：端点没配、请求失败、向量缺失，一律静默退回纯 BM25，不会白屏

先展示 BM25 结果，拿到向量后原地重排，所以感知延迟几乎为零。部署步骤见 **[VERCEL.md](VERCEL.md)**。

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
- 顺带标记 `is_review`（综述）、`high_impact`（高影响期刊）、`off_topic` + `rel_reason`（相关性判定结果与依据）

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
python scripts/fetch_abstracts.py  # 2. 回捞 Crossref 没给的摘要（无需 key）
python scripts/summarize.py        # 3. 中文摘要（需 key，增量）
python scripts/tag_papers.py       # 4. 自动打标 + 相关性判定（无需 key）
python scripts/prune_offtopic.py   # 5. 清理无关论文（删数据 + 记黑名单）
python scripts/build_embeddings.py # 6. 预计算向量（可选，需 embedding key，见 VERCEL.md）
python scripts/build_relations.py  # 7. 计算论文关联（无需 key）
python scripts/generate_site.py    # 8. 生成站点

open docs/index.html               # 或：cd docs && python -m http.server 8000
```

常用参数：

```bash
python scripts/fetch_papers.py            # 本地模式默认回看 7 天
python scripts/summarize.py --limit 20    # 本次只处理 20 篇，控制花费
python scripts/tag_papers.py --force      # 改词库后全量重标
python scripts/build_relations.py --force # 改关联算法后全量重算
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
