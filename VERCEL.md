# 语义检索代理（Vercel）

站是纯静态的，任何 key 都不能进前端。这个代理只做一件事：把一小段查询文本换成向量，
真正的 key 留在 Vercel 的环境变量里。

```
浏览器 ──POST /api/embed {text}──> Vercel Function ──> 服务商 /v1/embeddings
   ↑                                                      │
   └──────────── {v:[1024 个浮点数]} ←─────────────────────┘

文档向量不经过它 —— 那些由 scripts/build_embeddings.py 离线算好，
存成 docs/data/emb.bin（393 篇 × 1024 维 int8 ≈ 400 KB），浏览器直接拿走做点积。
```

## 1. 部署

仓库根目录已经有 `api/embed.js` 和 `vercel.json`，不用改代码。

**方式 A：网页导入**（推荐）

1. [vercel.com/new](https://vercel.com/new) → 选 `FC-Han/fishery-paper`
2. Framework Preset 选 **Other**，Root Directory 保持默认
3. Build Command 留空，Output Directory 填 `docs`
4. Deploy

**方式 B：命令行**

```bash
npm i -g vercel
cd fishery-paper
vercel --prod          # 首次会问项目名和目录，Output Directory 填 docs
```

部署完记下地址，形如 `https://fishery-paper-xxxx.vercel.app/api/embed`。

## 2. 环境变量

Vercel → 项目 → Settings → Environment Variables：

| 变量 | 必填 | 说明 |
|------|------|------|
| `EMBED_API_KEY` | ✅ | 服务商密钥，见下一节 |
| `EMBED_API_BASE` |  | 默认 `https://api.siliconflow.cn/v1/embeddings` |
| `EMBED_MODEL` |  | 默认 `BAAI/bge-m3` |
| `ALLOW_ORIGINS` |  | 默认 `https://fc-han.github.io,http://localhost:8000` |
| `DAILY_BUDGET` |  | 单实例每日放行上限，默认 3000，防刷爆额度 |

## 3. 选一家 embedding 服务

DeepSeek 只有 Chat Completions，**没有 `/embeddings` 接口**，必须另接一家。下面三家都是
OpenAI 兼容格式，改 `EMBED_API_BASE` + `EMBED_MODEL` 就能换：

| 服务商 | 模型 | 维度 | 地址 |
|--------|------|------|------|
| 硅基流动 | `BAAI/bge-m3` | 1024 | `https://api.siliconflow.cn/v1/embeddings` |
| 智谱 | `embedding-3` | 2048 | `https://open.bigmodel.cn/api/paas/v4/embeddings` |
| 阿里百炼 | `text-embedding-v4` | 1024 | `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings` |

**换模型后必须重跑 `build_embeddings.py --force`**，否则查询向量和文档向量不在同一个空间里，
余弦相似度全是噪声。

## 4. 大陆访问必须要自定义域名

`*.vercel.app` 在中国大陆被 DNS 污染，直接访问基本打不开。绑自己的域名即可绕开：

1. Vercel → Settings → Domains → 添加域名（如 `fishery-api.example.com`）
2. DNS 加一条 CNAME，指向 **`cname-china.vercel-dns.com`**
   （不是默认的 `cname.vercel-dns.com`，带 `-china` 的那个是 Vercel 给国内的入口）
3. 等 Vercel 显示两个绿勾

域名几十块一年。不绑域名的话，代理只在海外能用，国内用户搜索时会静默退回 BM25。

## 5. 打开站点上的语义检索

三处要串起来：

```bash
# ① Vercel 环境变量
EMBED_API_KEY=...            # 服务商 key
ALLOW_ORIGINS=https://fc-han.github.io

# ② GitHub 仓库 Settings → Secrets and variables → Actions
#    Secrets: EMBED_API_KEY
#    Variables: EMBED_API_BASE / EMBED_MODEL / EMBED_ENDPOINT

# ③ 重跑一次流水线（Actions → 渔业文献每日更新 → Run workflow）
#    它会重新算向量、并把 EMBED_ENDPOINT 写进 index.html
```

`EMBED_ENDPOINT` 是构建时烧进 HTML 的。留空 → 站点自动退回纯 BM25，不会报错、不会有空窗。

## 6. 本地验证

```bash
# 起一个假 embedding 服务，不花一分钱就能跑通链路
python - <<'EOF'
import hashlib, json, re
from http.server import BaseHTTPRequestHandler, HTTPServer
def vec(t):
    v=[0.0]*1024
    for k in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", t.lower()):
        h=int(hashlib.md5(k.encode()).hexdigest(),16); v[h%1024]+=1; v[(h>>11)%1024]+=0.5
    return v
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        b=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
        i=b.get('input') or b.get('text') or ''; i=i if isinstance(i,list) else [i]
        r=json.dumps({"data":[{"index":n,"embedding":vec(t)} for n,t in enumerate(i)]}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(r))); self.end_headers(); self.wfile.write(r)
    def do_OPTIONS(self): self.send_response(204); self.end_headers()
    def log_message(self,*a): pass
HTTPServer(('127.0.0.1',8931),H).serve_forever()
EOF

EMBED_API_KEY=x EMBED_API_BASE=http://127.0.0.1:8931/v1/embeddings python scripts/build_embeddings.py
EMBED_ENDPOINT=http://127.0.0.1:8931/v1/embeddings python scripts/generate_site.py
cd docs && python -m http.server 8000
```

假向量只能验证链路通不通，**别提交它生成的 `emb.bin`**。

## 7. 限额与排错

Hobby 免费额度：100 万次函数调用/月、4 CPU 小时、100 GB 流量 —— 这个场景一天几十次调用，
用不完。注意 **Hobby 仅限非商业用途**，超限是暂停 30 天而不是扣费。

| 现象 | 原因 |
|------|------|
| 403 `origin_not_allowed` | `ALLOW_ORIGINS` 里没加站点域名 |
| 429 `rate_limited` | 同 IP 每分钟超过 30 次 |
| 429 `daily_budget_exhausted` | 触到 `DAILY_BUDGET`，改大或等次日 |
| 504 `upstream_timeout` | 服务商 8 秒没返回，通常是网络问题 |
| 结果里没有「语义增强」 | `EMBED_ENDPOINT` 没烧进 HTML，或 `emb.json`/`emb.bin` 没生成 |

前端对语义检索是**先展示 BM25 结果、拿到向量后原地重排**，任何一步失败都静默退回 BM25，
不会白屏。
