# 🐟 渔业文献速览

> Fisheries Science Daily Digest — 每日自动抓取 · AI 中文速览 · 四维标签 · BM25 + 语义检索

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
| 🔗 论文关联 | 按**相似度阈值**自动关联相关文献（不设固定篇数、至少保底 1 篇），关系图分层呈现并可逐级探索 |
| 🔎 站内检索 | BM25 全文检索（标题/摘要/标签/期刊/作者），按相关度排序 + 关键词高亮，支持 `?q=` 分享链接 |
| 🧠 语义检索 | 可选：向量余弦 + BM25 混合排序，换个说法也能搜到；未配置时自动退回纯 BM25 |
| ⚡ 单文件站点 | 数据内联进 `index.html`，双击即可打开；英文摘要按需懒加载 |
| 🌗 体验 | 暗色模式、移动端抽屉式筛选、`/` 快捷搜索、`Esc` 关闭 |

## 🖼 页面结构

```
docs/
├── index.html            ← 全部页面（数据内联，约 626 KB）
└── data/
    ├── abstracts.json    ← 英文摘要，点"英文摘要"时才请求
    ├── papers.json       ← 完整结构化数据，可当 API 用
    ├── emb.json          ← 向量元信息（371 × 1024、模型名）
    └── emb.bin           ← 文档向量，int8 量化，约 371 KB（仅语义检索启用时存在）
```

## 🔗 论文关联

点卡片底部的「相关 N」展开推荐列表，点「关系图」进入可探索的关系网络：中心是当前论文，
四周是相关文献，点任意节点即以它为中心继续走，支持返回上一级。

**不设"每篇只看 4 篇"的硬上限**，改成用相似度阈值卡质量：

| 项 | 取值 | 说明 |
|---|---|---|
| 入榜门槛 | `MIN_SCORE = 0.25` | 0.13 时平均每篇 51 篇（共享主题 0.10 + 同刊 0.05 就过线），0.25 时中位 7 篇 |
| 数量 | 不设上限 | 平均 8 条、中位 7 条、最多 38 条（随论文量自然增长） |
| 至少 1 篇 | `FALLBACK_MIN = 0.08` | 没有一篇过阈值时，退让给最高分那篇并标「弱关联 ≈」，避免卡片出现孤岛 |

**算法**（`scripts/build_relations.py`，纯离线、零 API 成本，371 篇约 2 秒）：

- 文本相似：标题（权重 ×3）+ 英文摘要前 700 字符 + 中文速览，中英文分别按 bigram / 单词切分后做 TF-IDF 余弦
- 标签重叠：按共有的标签**个数**加分（同维度第 2 个减半），而非 Jaccard —— 共享 1 个鱼种本身就是强信号，不该被并集除小
- 融合：`0.45 × 文本 + 0.50 × 标签 + 0.05 × 同期刊`
- bigram TF-IDF 的绝对尺度很小（全体中位 0.012），所以文本分先按参考值 0.15 归一化再参与融合，否则会被压成噪声

**展示方式**（列表与图各司其职）：

- 列表：阈值内**全部**列出，视觉上前 6 条折叠，点「展开全部 N 篇」看全部
- 关系图（桌面）：≤7 篇单环；更多就分内外两环，按相关度从内到外填充（内环 6 + 外环 11 = 17 个节点容量），
  内环节点更大、代表强关联；超出画布容量时在底部注明「图内为相关度最高的 17 篇，另有 N 篇可在卡片列表查看」
- 关系图（窄屏）：竖排树状，容器内滚动，最多 16 个节点

结果写回 `data/papers.json` 的 `rel` 字段，生成站点时转成数组下标内联。
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

纯前端的轻量检索引擎，打开页面即在浏览器里建好索引：**零后端、零 API 成本**，349 篇的建索引 + 单次查询都在 10 ms 内。

- **分词**：中文不依赖词典，CJK 连续段切 bigram（"大黄鱼" → 大黄 / 黄鱼），英文按词，中英混排自动分开
- **字段加权**：标题 ×3.2、标签 ×2.2、期刊 ×1.8、摘要 ×1.0、作者 ×0.7，`k1=1.35`、`b=0.72` 做长度归一
- **多词查询**：先要求全部词项命中；查不到时按 IDF **从低区分度往高逐个丢词**，而不是一把退化成 OR。
  例如「大黄鱼 养殖」会守住"大黄+黄鱼"这个高区分度组合，只返回真正的黄鱼养殖文献
- **单字回退**：中文单字（如"鱼"）直扫原文，避免 bigram 索引漏召回
- **结果呈现**：按相关度排序，命中词在标题与摘要里高亮；关键词以标签形式显示在结果条上
- **可分享**：`.../index.html?q=大黄鱼` 直接打开就带着搜索结果

页面上按 `/` 可快速聚焦搜索框。

## 🧠 语义检索（可选）

BM25 只认字面，换个说法就搜不到了。搜「黄海」时，写 `Yellow Sea` 的论文一个都出不来；
搜「鱼的耳石」，`otolith` 那批也全军覆没。语义检索就是补这一块。

**两条通道并行，加权融合：**

```
             ┌── 字面通道：BM25 倒排索引（只认字面的字)
  查询 ──────┤
             └── 语义通道：embedding 向量（认意思，Bohai Sea 也算渤海）
                          ↓
                   0.55 × 字面 + 0.45 × 语义
```

为什么不是纯向量检索：物种拉丁名（`Siniperca chuatsi`）、作者名、期刊名这类精确查询，
BM25 一击必中，而向量反而会给你一堆"意思相近但物种不同"的论文。两条都要。

**向量怎么算的：**

| | 何时算 | 存哪 | 成本 |
|---|---|---|---|
| 文档向量（349 篇） | CI 里批量算，一天一次 | `docs/data/emb.bin`，int8 量化后 352 KB | **¥0**（免费模型） |
| 查询向量（每次搜索） | 浏览器实时请求 | 不存 | 走 Vercel 代理，key 不进前端 |

**关键实现参数：**

- 文本来源：标题 + 标签 + 英文摘要前段，喂给 `BAAI/bge-m3`（1024 维，中英混排都能用）
- 量化：L2 归一化后用 `int8` 存，压缩 4 倍且精度损失可忽略（余弦误差 < 0.002）
- 混合权重：`0.55 × BM25归一 + 0.45 × 余弦`
- 语义补充门槛：余弦 ≥ `0.34` 且不在 BM25 结果里，最多补 60 篇
- 请求超时：**6 秒**（Vercel 冷启动 1–2s + 服务商 0.5–1.5s，2.5s 会误杀正常请求）

> ⚠️ **模型 ID 别写成 `Pro/BAAI/bge-m3`。** 硅基流动对同一个模型提供免费版和 Pro 高速版：
> `BAAI/bge-m3` 费用为 0，`Pro/BAAI/bge-m3` 按 ¥0.07/百万 tokens 收费。本项目默认用前者。
>
> 免费模型不需要账户余额，未充值也能调用，但需完成实名认证；限额（RPM/TPM）是固定的，
> 提高付费消费也不会放宽，超限返回 429。`build_embeddings.py` 已带指数退避重试。
- 熔断：失败后 **5 分钟内不再重试**，避免端点不可达时反复拖累搜索

**降级策略：** 端点没配 / 向量缺失 / 请求失败 → 静默退回纯 BM25，页面不报错、不白屏。
但失败原因会打到浏览器控制台，方便排查：

```
[语义检索未生效] Failed to fetch
排查：1) 页面来源是否为 https://fc-han.github.io 2) /api/embed 能否 POST 通 3) Vercel 里 EMBED_API_KEY 是否已配
```

**交互设计：** 先渲染 BM25 结果 → 向量返回后原地重排。用户不会盯着空白页等，慢的时候只是排序晚一点变。

部署完整步骤见 **[VERCEL.md](VERCEL.md)**，踩过的坑也记在里面。

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

分两层：**基础站（必须）** 和 **语义检索（可选）**。只做第一层就能完整使用除语义搜索外的全部功能。

### 第一层：基础站（5 分钟）

| # | 在哪 | 做什么 |
|---|---|---|
| 1 | GitHub → Settings → Secrets and variables → Actions → **Secrets** | 加 `DEEPSEEK_API_KEY`（[申请](https://platform.deepseek.com/)） |
| 2 | GitHub → 同页 → **Variables** | 可选：`SEMANTIC_SCHOLAR_API_KEY` |
| 3 | GitHub → Settings → **Pages** | Source 选 `Deploy from a branch`，分支 `main`、目录 `/docs` |
| 4 | GitHub → Actions | 启用 workflow（首次会自动跑一次） |
| 5 | Actions → 渔业文献每日更新 → **Run workflow** | 手动触发，等 2–4 分钟 |

跑完访问 `https://<用户名>.github.io/fishery-paper/`。之后每天北京时间 16:00 自动更新
（回看 5 天，靠 DOI 去重，避免索引延迟漏文）。

### 第二层：语义检索（可选，约 15 分钟）

需要额外的 embedding 服务 + 一个 serverless 代理。完整步骤见 **[VERCEL.md](VERCEL.md)**，简版：

| # | 在哪 | 做什么 |
|---|---|---|
| 1 | [cloud.siliconflow.cn](https://cloud.siliconflow.cn) | 注册，新建 API 密钥，拿到 `sk-xxx` |
| 2 | [vercel.com/new](https://vercel.com/new) | 导入本仓库，**Application Preset 必须选 `Other`**（会被误判成 Python），Output Directory 填 `docs` |
| 3 | Vercel → Settings → Environment Variables | 加 `EMBED_API_KEY` |
| 4 | GitHub → Settings → Secrets | 加 `EMBED_API_KEY`（同一个 key） |
| 5 | GitHub → Settings → Variables | 加 `EMBED_API_BASE`、`EMBED_MODEL`、`EMBED_ENDPOINT` |
| 6 | Actions → Run workflow | 重新构建，把端点烧进 HTML 并生成向量 |

详细取值、踩坑记录、排错表都在 **[VERCEL.md](VERCEL.md)**。

## 📋 更新记录

见 **[CHANGELOG.md](CHANGELOG.md)**。

## 💰 成本

| 项目 | 开销 |
|------|------|
| Crossref / OpenAlex / Semantic Scholar | 免费 |
| GitHub Actions / Pages | 免费 |
| DeepSeek（约 20 篇/天） | ≈ ¥0.03/天，¥1/月 |
| embedding（向量） | **¥0**。`BAAI/bge-m3` 在硅基流动价格页标注「免费」，费用为 0、不消耗余额（限额固定，超了返回 429） |
| Vercel | Hobby 免费（100 万次调用/月），本场景用量不到千分之一 |

## 📊 文献来源

**渔业与水产期刊（27 本）**：Fisheries Research · Fish and Fisheries · ICES JMS · CJFAS · TAFS · North American JFM · Reviews in Fish Biology and Fisheries · Reviews in Fisheries Science & Aquaculture · Fisheries Management and Ecology · Fisheries Oceanography · Fisheries Science · Aquaculture · Aquaculture Reports · Aquaculture International · Aquaculture Research · Reviews in Aquaculture · Journal of Fish Biology · Journal of Fish Diseases · Ecology of Freshwater Fish · Journal of Applied Ichthyology · Fishes · MEPS · Marine Policy · Marine Pollution Bulletin · Frontiers in Marine Science · Hydrobiologia · ECSS

**综合期刊**：Nature · Science · PNAS · Nature Climate Change · Nature Ecology & Evolution · Nature Sustainability · Nature Communications · Science Advances · Scientific Data

## 📝 License

MIT
