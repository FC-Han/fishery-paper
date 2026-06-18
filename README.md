# 🐟 渔业文献每周速览

> Fisheries Science Weekly Digest — AI 驱动 · DeepSeek 中文总结 · 每日自动更新

[![Weekly Update](https://github.com/FC-Han/fishery-paper/actions/workflows/daily-update.yml/badge.svg)](https://github.com/FC-Han/fishery-paper/actions/workflows/daily-update.yml)

## ✨ 功能特点

- 🔍 **全面覆盖** — 标题搜索 + 18本渔业期刊 + Nature/Science/PNAS 等综合期刊
- 🤖 **DeepSeek AI** — 每篇论文中文摘要 + 每周综述标题 + 每周研究关键词
- 📅 **多页面架构** — 主页轻量（~8KB），每周独立详情页，不卡顿
- 🎨 **精美展示** — 海洋主题响应式设计、暗色模式、实时搜索
- ⏰ **每日自动** — GitHub Actions 每日 UTC 8:00 自动运行
- 💰 **几乎免费** — DeepSeek API 极低价格，日均不到 ¥0.05

## 🏗 页面架构

```
docs/
├── index.html              ← 主页（每周综述卡片，8KB）
├── week-2026-W25.html      ← 第25周详情（论文列表，~130KB）
├── week-2026-W24.html      ← 第24周详情
└── ...
```

主页点击任意周卡片 → 跳转到该周详情页 → 浏览全部论文 + 中文总结

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone git@github.com:FC-Han/fishery-paper.git
cd fishery-paper
cp .env.example .env
```

### 2. 获取 API Key

- **DeepSeek API**（必需）：https://platform.deepseek.com/ → 注册充值 10 元可用数月
- **Semantic Scholar**（可选）：https://www.semanticscholar.org/product/api

### 3. 本地测试

```bash
pip install -r requirements.txt
python scripts/fetch_papers.py           # 获取论文（无需 API key）
python scripts/summarize.py              # AI 中文总结（需要 DEEPSEEK_API_KEY）
python scripts/generate_site.py          # 生成多页面站点
open docs/index.html                     # 浏览器预览
```

### 4. GitHub 部署

**设置 Secret：**
`Settings > Secrets and variables > Actions` → 添加 `DEEPSEEK_API_KEY`

**启用 Pages：**
`Settings > Pages` → Source: `Deploy from a branch` → `main` / `/docs`

**手动触发：**
`Actions > 渔业文献每周更新 > Run workflow`

## 💰 费用对比

| 服务 | 每日 | 每月 |
|------|------|------|
| DeepSeek API | ~¥0.03 | ~¥1 |
| Crossref API | 免费 | 免费 |
| GitHub Actions | 免费 | 免费 |
| **合计** | **~¥0.03** | **~¥1** |

## 📊 文献来源

**渔业专业期刊：** Fisheries Research · Fish and Fisheries · ICES JMS · CJFAS · TAFS · Aquaculture · J. Fish Biology · Fisheries Oceanography · Marine Policy · MEPS 等 18 本

**综合期刊：** Nature · Science · PNAS · Nature Climate Change · Nature Ecology & Evolution · Nature Sustainability · Nature Communications · Science Advances

## 📝 License

MIT
