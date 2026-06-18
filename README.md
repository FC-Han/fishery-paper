# 🐟 渔业文献每周速览

> Fisheries Science Weekly Digest — 自动获取最新渔业期刊论文，AI 生成中文总结，每周综述

[![Weekly Update](https://github.com/{{REPO}}/actions/workflows/daily-update.yml/badge.svg)](https://github.com/{{REPO}}/actions/workflows/daily-update.yml)

## ✨ 功能特点

- 🔍 **全面覆盖** — 标题精确搜索 + 18 本渔业专业期刊 + Nature/Science/PNAS 等综合期刊
- 🤖 **AI 双总结** — 每篇论文中文摘要 + 每周综述标题（Claude Haiku 驱动）
- 📅 **每周综述** — 按周分组，AI 生成每周研究热点标题，点击展开查看全部论文
- 🎨 **精美展示** — 海洋主题响应式页面，暗色模式，实时搜索
- ⏰ **每日自动** — GitHub Actions 每日运行，自动更新文献库
- 💰 **几乎免费** — 日均 API 费用不到 1 美分

## 🔐 关于 API Key 安全性

**GitHub Actions Secrets 是安全可靠的：**
- AES-256 加密存储
- 只在 Actions 运行时解密
- 日志中自动屏蔽（显示为 `***`）
- 只有仓库管理员能查看/修改
- 这是 GitHub 官方推荐的做法，被数十万项目使用

**如果你仍想在本地运行总结：**
```bash
# 在 .env 中设置 ANTHROPIC_API_KEY
python scripts/summarize.py
python scripts/generate_site.py
git add data/ docs/ && git commit -m "手动更新" && git push
```

## 🚀 快速开始

### 1. 创建仓库

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
cp .env.example .env
```

### 2. 获取 API Keys

- **Claude API**（必需）：https://console.anthropic.com/ → 创建 API key
- **Semantic Scholar**（可选）：https://www.semanticscholar.org/product/api → 免费注册

### 3. 本地测试

```bash
pip install -r requirements.txt

# 获取论文（无需 API key）
python scripts/fetch_papers.py

# 生成 AI 总结（需要 ANTHROPIC_API_KEY）
python scripts/summarize.py

# 生成 HTML
python scripts/generate_site.py
# 浏览器打开 docs/index.html 查看效果
```

### 4. 配置 GitHub

**设置 Secrets：**
`Settings > Secrets and variables > Actions > New repository secret`
- `ANTHROPIC_API_KEY` = 你的 Claude API key
- `SEMANTIC_SCHOLAR_API_KEY` = 你的 S2 API key（可选）

**启用 GitHub Pages：**
`Settings > Pages` → Source: `Deploy from a branch` → Branch: `main`, Folder: `/docs`

### 5. 首次运行

`Actions > 渔业文献每周更新 > Run workflow` 手动触发即可。

网站地址：`https://YOUR_USERNAME.github.io/YOUR_REPO/`

## 📁 项目结构

```
.
├── .github/workflows/daily-update.yml
├── scripts/
│   ├── fetch_papers.py        # 论文获取（3层搜索策略）
│   ├── summarize.py           # AI 总结 + 每周综述
│   └── generate_site.py       # HTML 生成
├── templates/
│   └── index.html.jinja2      # 每周综述模板
├── data/papers.json           # 论文数据
├── docs/index.html            # 生成的站点 ✨
└── requirements.txt
```

## 📊 文献来源

### 渔业专业期刊（18本）
Fisheries Research · Fish and Fisheries · ICES J. Marine Science · Canadian J. Fisheries · Trans. American Fisheries Society · Reviews in Fish Biology · Aquaculture · J. Fish Biology · Fisheries Oceanography · Marine Policy · Reviews in Fisheries Science · Fisheries Science · Marine Ecology Progress Series · Marine Pollution Bulletin 等

### 综合期刊
Nature · Science · PNAS · Nature Climate Change · Nature Ecology & Evolution · Nature Sustainability · Nature Communications · Science Advances · Scientific Data

## 💰 费用

| 项目 | 每日 | 每月 |
|------|------|------|
| Claude Haiku API | ~$0.005 | ~$0.15 |
| Crossref API | 免费 | 免费 |
| Semantic Scholar | 免费 | 免费 |
| GitHub Actions | 免费 | 免费 |
| **合计** | **~$0.005** | **~$0.15** |

## 📝 License

MIT
