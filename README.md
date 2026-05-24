# woshipm-publisher

人人都是产品经理(woshipm.com) 全栈运营技能：AI 驱动的评论区获客 + 热点获客发文。

[![version](https://img.shields.io/badge/version-1.1.0-blue)](https://github.com/jiashaoshan/woshipm-publisher)
[![python](https://img.shields.io/badge/python-3.8+-green)](https://www.python.org/)

## 功能

### 评论区获客 ✅

输入一个产品链接，自动完成：

1. **理解产品** — 抓取产品网站 meta 信息，知道产品是做什么的
2. **生成关键词** — LLM 产出 8 个搜索关键词
3. **搜索文章** — 在 woshipm 搜索文章(tab=0) 和问答(tab=2)
4. **智能筛选** — 四维评分：曝光机会 + 内容质量 + 作者活跃 + 互动健康
5. **生成评论** — LLM 阅读全文，结合产品信息，生成自然评论
6. **自动发表** — WordPress 评论接口自动发表

### 热点获客发文 ✅

TrendRadar 获取热点 → LLM 产品分析 → AI 挑选最佳热点 → LLM 生成获客文章 → Pexels 封面 → 发布

1. **产品分析** — 抓取产品链接，LLM 结构化分析（产品名/卖点/痛点/功能）
2. **热点获取** — 从 TrendRadar MCP 获取多平台热点
3. **AI 挑选** — 自动匹配最适合与产品结合的热点
4. **文章生成** — LLM 生成 1500-3000 字获客文章（产品软植入，纯文本无 Markdown）
5. **封面图** — Pexels 搜索并下载到本地 `data/covers/`
6. **发布** — 通过 BrowserWing 发布（需先录制脚本）

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

# 正式发布（需先录制 BW 脚本）
export WOSHIPM_PUBLISH_SCRIPT_ID="你的BW脚本ID"
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
                      BrowserWing 发布或存为草稿
```

### BrowserWing 发布

热点获客发文使用 BrowserWing 自动化发布。使用前需：
1. 在 BrowserWing 录制一个 woshipm 写文章脚本
2. 脚本变量：`标题`、`正文`、`封面`
3. 设置环境变量 `WOSHIPM_PUBLISH_SCRIPT_ID`

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
| 文章发布 | BrowserWing 浏览器自动化 |

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
