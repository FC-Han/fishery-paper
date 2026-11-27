# 语义检索部署指南（Vercel）

站是纯静态的，任何 key 都不能进前端。这个代理只做一件事：把一小段查询文本换成向量，
真正的 key 留在 Vercel 的环境变量里。

```
浏览器 ──POST /api/embed {text}──> Vercel Function ──> 服务商 /v1/embeddings
   ↑                                                      │
   └──────────── {v:[1024 个浮点数]} ←─────────────────────┘

文档向量不经过它 —— 那些由 scripts/build_embeddings.py 离线算好，
存成 docs/data/emb.bin（349 篇 × 1024 维 int8 ≈ 352 KB），浏览器直接拿走做点积。
```

---

## 0. 需要准备什么

| 东西 | 必需 | 说明 |
|---|---|---|
| GitHub 仓库 | ✅ | 本仓库，且已启用 Actions + Pages |
| [硅基流动](https://cloud.siliconflow.cn) 账号 | ✅ | 拿 embedding key，`BAAI/bge-m3` 费用为 0 |
| [Vercel](https://vercel.com) 账号 | ✅ | GitHub 直接登录，Hobby 免费计划即可 |
| 自有域名 | ❌ 可选 | 只有大陆访客需要，见第 5 节 |

**成本**：embedding 走的是免费模型，**费用为 0，不需要充值**（349 篇文档向量一天一批、
查询向量一天几十次，账单里都显示 0）。Vercel Hobby 是 100 万次调用/月，用量不到千分之一。

> 免费模型的前提：完成**实名认证**；模型 ID 必须是 `BAAI/bge-m3`，
> 写成 `Pro/BAAI/bge-m3` 就变成收费版（¥0.07/百万 tokens）。
> 限额（RPM/TPM）固定，不随付费消费提高，超限返回 429。

---

## 1. 拿 embedding key

1. [cloud.siliconflow.cn](https://cloud.siliconflow.cn) 注册（手机号即可），
   按控制台提示完成**实名认证**（未认证无法使用免费模型，会返回 403）
2. 左侧「API 密钥」→ 新建密钥
3. 复制 `sk-...`，**只显示一次**，先存到记事本

**不需要充值。** 价格页标注「免费」的模型费用为 0，账单里消耗显示 0，余额为 0 也能调。

> DeepSeek 只有 Chat Completions，**没有 `/embeddings` 接口**，所以必须另接一家。
> 硅基流动的 `BAAI/bge-m3` 免费、中英混排效果好、1024 维。

---

## 2. 部署到 Vercel

1. 打开 [vercel.com/new](https://vercel.com/new)，选 `FC-Han/fishery-paper`
2. **Project Name**：随意，默认 `fishery-paper` 即可（决定域名）
3. **Root Directory**：保持 `./`，**不要填 docs**
4. **Application Preset**：改成 **`Other`** ⚠️
5. 展开 **Build and Output Settings**：
   - Build Command：**留空**
   - Output Directory：**`docs`**
   - Install Command：留空
6. 展开 **Environment Variables**，加一条：
   - `EMBED_API_KEY` = 第 1 步的 key
   - 环境勾 **Production**（Preview 也勾上更省事）
7. 点 **Deploy**

### ⚠️ Application Preset 必须选 Other

Vercel 会"看文件猜框架"：仓库根目录有 `requirements.txt` 和 `scripts/*.py`，
它会自动选成 **Python**。但我们的 Python 只是定时抓数据的离线脚本，**根本不跑在 Vercel 上**。

选成 Python 的后果：`api/embed.js` 不会被打包成函数，访问 `/api/embed` 永远 404，
而静态页面却能正常打开——症状非常迷惑。

### 部署完先验证，别急着往下走

访问 `<你的域名>/api/embed`（浏览器直接打开，GET 请求）：

```json
{"ok":true,"model":"BAAI/bge-m3"}
```

| 结果 | 说明 |
|---|---|
| 上面这行 JSON | ✅ 函数正常，继续第 3 步 |
| 404 `NOT_FOUND` | Preset 没选 Other，或 Root Directory 填成了 docs |
| 500 `missing_key` | `EMBED_API_KEY` 没配，或配了没 Redeploy |
| 401 / 要求登录 | Deployment Protection 开着，去 Settings → Deployment Protection 关掉 |

`model` 字段显示 `BAAI/bge-m3` 说明默认值兜底生效，你在 Vercel 那边不配 `EMBED_MODEL` 也行。

---

## 3. 配 GitHub 仓库

进 GitHub 仓库 → **Settings → Secrets and variables → Actions**。注意这里有**两个标签页**，
放错位置不会报错，只会拿到空字符串然后静默跳过。

### Secrets 标签页（1 条）

点 `New repository secret`：

| Name | Secret |
|---|---|
| `EMBED_API_KEY` | 和第 1 步、Vercel 里**完全同一个** key |

### Variables 标签页（3 条）

点三次 `New repository variable`，一条一条加：

| Name | Value |
|---|---|
| `EMBED_API_BASE` | `https://api.siliconflow.cn/v1/embeddings` |
| `EMBED_MODEL` | `BAAI/bge-m3` |
| `EMBED_ENDPOINT` | `https://<你的域名>/api/embed` |

三条的作用不同：

- `EMBED_API_BASE` / `EMBED_MODEL` → **构建脚本**用，算 349 篇文档向量
- `EMBED_ENDPOINT` → **前端**用，构建时直接烧进 `index.html`，告诉浏览器往哪发请求

> `EMBED_ENDPOINT` 是**构建时常量**。填错或漏填都必须重新跑一次流水线，改完立刻生效是不可能的。

---

## 3.5 问答（RAG，可选）

右上角的「问一问」走同一个 Vercel 项目里的第二个函数 `api/ask.js`：前端先用 `emb.bin` 召回十来篇，
再把标题和摘要发给 DeepSeek 生成答案。**不配也能用**，只是点开只给依据、不生成答案。

### Vercel 加一个密钥

Settings → Environment Variables → 新增：

| Name | Value | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | `sk-...` | 和 GitHub Secrets 里那个是**同一个**，但 Vercel 是独立环境，必须单独加 |

加完要 **Redeploy** 一次（Deployments → 最新一条 → ⋯ → Redeploy），否则函数读到的还是旧环境。

### GitHub 加一个变量

Variables 标签页：

| Name | Value |
|---|---|
| `ASK_ENDPOINT` | `https://<你的域名>/api/ask` |

和 `EMBED_ENDPOINT` 一样，这是**构建时常量**，必须重跑流水线才会烧进页面。

### 验证

浏览器打开 `https://<你的域名>/api/ask`，应返回：

```json
{"ok":true,"model":"deepseek-chat"}
```

然后回站点问一句「深水网箱养殖的病害研究进展」：正常会看到分段答案，每个论点后面挂着绿色编号，
点编号跳到对应论文的卡片。

| 现象 | 原因 |
|---|---|
| 只出依据、没有答案 + 标「降级」 | `DEEPSEEK_API_KEY` 没配 / 没 redeploy / 余额不足 |
| `生成服务没连上` | 跨域被拦：确认 `ALLOW_ORIGINS` 里有你的站点域名 |
| 答案里编号引用了不存在的文献 | 模型自己编的，`api/ask.js` 的 system prompt 已约束，仍可能出现，看依据列表为准 |

> 费用：一次提问约 3–6k token，DeepSeek 下 ≈ 0.005 元。函数内有 6 次/分/IP 限流和每日 300 次软预算。

---

## 4. 重跑流水线

GitHub → **Actions** → 左侧 `渔业文献每日更新` → 右侧 **Run workflow**。

跑 2–4 分钟，日志里应该有：

```
🧠 预计算论文向量
✅ 349 篇 · 1024 维 · int8 量化 · 约 352 KB
```

**不重跑等于没配**——页面里还是空端点，前端会当成没接语义检索。

### 验证真的点亮了

打开站点搜一个中文词，比如「黄海」：

| 现象 | 说明 |
|---|---|
| 结果条出现青色 **语义增强** 标签 | ✅ 通了 |
| 结果数比纯 BM25 明显变多 | 语义补充候选生效 |
| 标签没有，但功能正常 | 降级了，按第 7 节排错 |

鼠标悬停在「语义增强」上会显示细节：`BM25 与向量余弦混合排序，语义补充 N 篇`。

---

## 5. 大陆访问与自定义域名（可选）

`*.vercel.app` 在中国大陆的 DNS 解析不稳定，**打不开时会静默降级为纯 BM25**，功能不坏但用不上。

实测有些域名能通、有些不能，和你所在网络有关。如果你和访客都能打开，可以先用着；
要稳定就绑自有域名：

1. Vercel → Settings → **Domains** → 添加域名（如 `fishery-api.example.com`）
2. DNS 加一条 CNAME，指向 **`cname-china.vercel-dns.com`**
   - 注意不是默认的 `cname.vercel-dns.com`，带 `-china` 的那个才是 Vercel 给国内的入口
3. 等 Vercel 显示两个绿勾
4. 回 GitHub 把 `EMBED_ENDPOINT` 改成 `https://fishery-api.example.com/api/embed`
5. **再跑一次流水线**（端点变了必须重建）

域名几十块一年。

---

## 6. 换一家 embedding 服务

三家都是 OpenAI 兼容格式，改 `EMBED_API_BASE` + `EMBED_MODEL` 就能换：

| 服务商 | 模型 | 维度 | 地址 |
|---|---|---|---|
| 硅基流动 | `BAAI/bge-m3` | 1024 | `https://api.siliconflow.cn/v1/embeddings` |
| 智谱 | `embedding-3` | 2048 | `https://open.bigmodel.cn/api/paas/v4/embeddings` |
| 阿里百炼 | `text-embedding-v4` | 1024 | `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings` |

**换模型后必须重跑 `build_embeddings.py --force`**。

原因：文档向量和查询向量必须在同一个语义空间里。换了模型但沿用旧 `emb.bin`，
两边的向量互不对应，余弦相似度全是噪声——而且不会报错，只是搜出来的结果毫无关联。

---

## 7. 排错

### 先看控制台

前端失败会在浏览器 Console 打一条警告：

```
[语义检索未生效] Failed to fetch
排查：1) 页面来源是否为 https://fc-han.github.io 2) /api/embed 能否 POST 通 3) Vercel 里 EMBED_API_KEY 是否已配
```

### 手动测一次 POST

Console 里粘贴，能一次定位问题层：

```js
fetch('https://<你的域名>/api/embed', {
  method:'POST',
  headers:{'Content-Type':'application/json'},
  body: JSON.stringify({text:'黄海'})
}).then(r=>r.json()).then(j=>console.log(j.dim, j.v?.slice(0,3)))
  .catch(e=>console.error('失败', e.message))
```

### 错误码对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 404 `NOT_FOUND` | 函数没被打包 | Preset 没选 Other / Root Directory 填了 docs |
| 403 `origin_not_allowed` | 页面来源不在白名单 | Vercel 加环境变量 `ALLOW_ORIGINS`，把站点域名加进去 |
| 500 `missing_key` | Vercel 缺 `EMBED_API_KEY` | 补上后 **Redeploy** |
| 429 `rate_limited` | 同 IP 每分钟超 30 次 | 正常保护，等一下即可 |
| 429 `daily_budget_exhausted` | 触到 `DAILY_BUDGET` | 默认 3000，改大或等次日 |
| 504 `upstream_timeout` | 服务商 8 秒没返回 | 检查 `EMBED_API_BASE` 是否正确 |
| 502 `upstream_error` | 服务商返回错误 | 看响应里的 `detail`，多半是 key 或模型名错了 |
| 请求报 CORS 错误 | 来源不在白名单 | 同上，配 `ALLOW_ORIGINS` |
| 通了但页面没标签 | `EMBED_ENDPOINT` 没烧进 HTML | 重跑流水线 |
| 有标签但结果很怪 | 换过模型没重算向量 | `build_embeddings.py --force` |

### Vercel 环境变量（都在 Settings → Environment Variables）

| 变量 | 必填 | 默认值 |
|---|---|---|
| `EMBED_API_KEY` | ✅ | — |
| `EMBED_API_BASE` | | `https://api.siliconflow.cn/v1/embeddings` |
| `EMBED_MODEL` | | `BAAI/bge-m3` |
| `ALLOW_ORIGINS` | | `https://fc-han.github.io,https://fishery-paper.vercel.app,http://localhost:8000,http://127.0.0.1:8000` |
| `DAILY_BUDGET` | | `3000` |

---

## 8. 本地调试（不花钱）

用假向量跑通整条链路：

```bash
python _mock_embed.py 8931     # 起一个本地假 embedding 服务

EMBED_API_KEY=x EMBED_API_BASE=http://127.0.0.1:8931/v1/embeddings \
  python scripts/build_embeddings.py

EMBED_ENDPOINT=http://127.0.0.1:8931/v1/embeddings \
  python scripts/generate_site.py

cd docs && python -m http.server 8000
```

三个必须注意的点：

1. **`file://` 打不开语义链路**——`fetch` 跨协议受限，必须起 HTTP 服务
2. **假向量生成的 `emb.bin` 绝不能提交**，它只验证管道通不通，没有语义
3. 假服务要同时接受 `input`（服务商格式）和 `text`（本项目代理格式），否则前端拿到全零向量，
   表现为 `maxcos=0` 但代码不报错——很难查

---

## 附：几个容易踩的坑

| 坑 | 表现 | 原因 |
|---|---|---|
| Application Preset 自动选成 Python | `/api/embed` 404，页面正常 | 仓库里有 `requirements.txt` 和 `.py` 文件 |
| Root Directory 填成 `docs` | 同上 | 函数在仓库根，不在 docs 里 |
| 环境变量放错标签页 | 静默不生效 | `secrets.` 和 `vars.` 是两个命名空间 |
| 改完变量没 Redeploy | 函数读旧值 | Vercel 环境变量只对**新部署**生效 |
| 用部署 ID 域名做端点 | 永远跑旧代码 | `xxx-7xu5vn9i3-yyy.vercel.app` 是某次部署的固定地址，每次提交都变 |
| 大陆访问不通 | 静默降级 | `*.vercel.app` 解析不稳定，需绑自有域名 |

**关于域名怎么选**：用生产别名或分支别名，别用带部署 ID 的：

```
✅ https://fishery-paper.vercel.app/api/embed              # 生产别名
✅ https://fishery-paper-git-main-xxx.vercel.app/api/embed # main 分支最新
❌ https://fishery-paper-7xu5vn9i3-xxx.vercel.app/api/embed # 某次部署，写死了
```
