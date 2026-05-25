# woshipm-publisher

人人都是产品经理(woshipm.com) 全栈运营技能：AI 驱动的评论区获客 + 热点获客发文。

[![version](https://img.shields.io/badge/version-1.2.0-blue)](https://github.com/jiashaoshan/woshipm-publisher)
[![python](https://img.shields.io/badge/python-3.8+-green)](https://www.python.org/)

## 功能

### 评论区获客 ✅

输入一个产品链接，自动完成：

1. **理解产品** — 抓取产品网站内容，知道产品是做什么的
2. **生成关键词** — LLM 产出 8 个搜索关键词
3. **搜索文章** — 在 woshipm 搜索文章(tab=0) 和问答(tab=2)
4. **智能筛选** — 四维评分：曝光机会 + 内容质量 + 作者活跃 + 互动健康
5. **生成评论** — LLM 阅读全文，结合产品信息，生成自然评论
6. **自动发表** — WordPress 评论接口自动发表

### 热点获客发文 ✅

RSS热点(AI/科技类) → LLM 产品分析 → AI 挑选最佳热点 → LLM 生成行业分析文章 → Pexels 封面 → WordPress 发布

1. **产品分析** — 抓取产品链接，LLM 结构化分析（产品名/卖点/痛点/功能）
2. **热点获取** — 从 AI/产品类 RSS 获取（新智元、量子位、Hacker News 优先，降级 36氪/知乎/V2EX/掘金）
3. **AI 挑选** — 以产品经理选题策划视角，匹配最适合的热点
4. **文章生成** — LLM 生成 1000-2000 字行业分析文章，产品作为案例自然出现
5. **封面图** — Pexels 搜索并下载到本地 `data/covers/`
6. **发布** — 通过 WordPress AJAX API 提交审核

### v1.2 更新内容

| 改动 | 之前 | 之后 |
|------|------|------|
| 热点源 | 全平台热榜（含娱乐/体育/社会） | AI/科技类 RSS（新智元、量子位、Hacker News） |
| 文章定位 | 热点切入→安利产品 | 产品经理视角的行业分析，产品作为案例 |
| AI选热点 | 营销策略专家 | PM 选题策划 |
| 文章角度 | 技术实现/工具评测 | 产品设计/商业模式/行业趋势/选型思路 |
| 产品出现 | "原来还有这种好东西" | 作为行业案例/解决思路自然提及 |
| 标题风格 | 可含产品名 | 像正常行业分析文章 |

## 快速开始

### 1. 安装

```bash
pip install cloudscraper requests beautifulsoup4
```

### 2. LLM 配置

编辑 `config/llm.json`，填入 API Key：
```json
{
  "provider": "baiduqianfancodingplan",
  "api_key": "bce-v3/your-api-key",
  "model": "qianfan-code-latest"
}
```

### 3. Cookie 配置

```bash
cp .env woshipm.env
# 编辑填入 Cookie（登录 woshipm.com → F12 → Application → Cookies → 复制全部值）
```

### 4. 运行

```bash
# ── 评论区获客（测试） ──
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" --dry-run

# 正式运行
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" --max-comments 10 --max-answers 3

# ── 热点获客发文（测试） ──
python3 scripts/woshipm-hotspot-publish.py \
  --product-url "https://your-product.com" --dry-run

# 正式发布
# 确保 .env 中已配置 WOSHIPM_COOKIE
python3 scripts/woshipm-hotspot-publish.py \
  --product-url "https://your-product.com"

# ── 独立搜索 ──
python3 scripts/woshipm_search.py --keyword "产品经理"
```

## 热点获客发文流程

```
产品 URL → 页面抓取 → LLM 结构化分析
                                ↓
                      TrendRadar 获取多平台热点
                                ↓
                      AI 挑选最佳匹配热点
                                ↓
                      LLM 生成获客文章（软植入）
                                ↓
                      Pexels 封面本地下载
                                ↓
                      WordPress AJAX API 提交审核
                              (action=add_pending)
                                ↓
                      保存草稿或直接发布（通过 admin-ajax.php）
```

### 发布说明

热点获客发文通过 WordPress `admin-ajax.php` 发布，使用 `action=add_pending` 提交审核。

需在 `.env` 中配置登录 Cookie：

## LLM 配置

LLM 配置统一为 `config/llm.json`，支持 provider：
- `baiduqianfancodingplan` — 百度千帆 Coding Plan（默认）
- `deepseek` — DeepSeek API
- `sensenova` —  senseNova

```json
{
  "provider": "baiduqianfancodingplan",
  "api_key": "bce-v3/xxx",
  "model": "qianfan-code-latest"
}
```

## 技术栈

| 模块 | 技术 |
|------|------|
| LLM | 百度千帆 Coding Plan API（OpenAI 兼容） |
| 搜索 | `api.woshipm.com` AJAX 端点 |
| 页面抓取 | `cloudscraper` 穿透 Cloudflare |
| 评论发表 | WordPress `wp-comments-post.php` |
| 热点数据 | TrendRadar MCP |
| 封面图 | Pexels API，下载到本地 |
| 文章发布 | WordPress `admin-ajax.php`（`action=add_pending/add_draft`）|

## 目录结构

```
woshipm-publisher/
├── SKILL.md                          # 技术设计文档
├── README.md                         # 本文件
├── _meta.json                        # 技能元数据
├── .env                              # Cookie 配置
├── woshipm_acquisition_config.json   # 获客策略配置
│
├── config/                           # LLM 配置
│   ├── llm.json                      # provider/api_key/model
│   └── llm.template.json             # 模板
│
├── scripts/
│   ├── woshipm_acquisition.py        # 评论区获客
│   ├── woshipm_search.py             # 独立搜索
│   ├── woshipm-hotspot-publish.py    # ★ 热点获客发文
│   └── zhihu_llm.py                  # LLM 调用封装
│
├── templates/                        # LLM 提示词模板
│   ├── product-analysis-prompt.md    # 产品分析
│   └── hotspot-acquisition-prompt.md # 获客文章
│
├── output/                           # 生成文章预览
└── data/
    ├── covers/                       # Pexels 封面图本地缓存
    ├── commented-history.json
    └── answered-history.json
```
