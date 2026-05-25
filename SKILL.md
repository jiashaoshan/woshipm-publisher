---
name: woshipm-publisher
description: |
  人人都是产品经理(woshipm)全栈运营：评论区获客(AI评论+问答回答) + 热点获客发文
  基于 WordPress admin-ajax.php API 和百度千帆 API 驱动 AI 内容生成
metadata:
  openclaw:
    emoji: "📢"
    requires:
      env: ["WOSHIPM_COOKIE"]
    category: "acquisition"
    tags: ["woshipm", "acquisition", "publish", "hotspot", "ai"]
---

# woshipm-publisher

人人都是产品经理(woshipm.com) 全栈运营技能。

---

## 架构总览

```
                          woshipm-publisher
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
   │ 评论区获客    │   │  独立搜索     │   │  热点获客发文     │
   │ v1.0 ✅      │   │  v1.0 ✅     │   │  v1.0 ✅          │
   └──────────────┘   └──────────────┘   └──────────────────┘
```

## 功能矩阵

| 功能 | 说明 | 关联脚本 |
|------|------|----------|
| 🎯 评论区获客 | 搜索 → 四维评分 → LLM评论 → WordPress API 发表 | `woshipm_acquisition.py` |
| 🔍 独立搜索 | 关键词搜索 woshipm 文章 | `woshipm_search.py` |
| 🔥 热点获客发文 | TrendRadar RSS(新智元/量子位/Hacker News) → 产品分析 → AI挑选 → LLM生成行业分析文章 → Pexels封面 → WordPress API 发布 | `woshipm-hotspot-publish.py` |

---

## 模块一：评论区获客 v1.0

### 流程设计

```
                    输入：产品 URL
                         │
              ┌──────────▼──────────┐
              │  抓取产品页面信息     │
              │  (meta description) │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │  LLM 生成 8 个关键词  │
              │  (宽泛 3 + 精准 5)    │
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼                               ▼
  ┌──────────────┐               ┌──────────────┐
  │ 搜索文章 tab=0│               │ 搜索问答 tab=2│
  │ 时间排序 ×5页 │               │ 时间排序 ×5页 │
  └──────┬───────┘               └──────┬───────┘
         │                               │
         └───────────────┬───────────────┘
                         │
              ┌──────────▼──────────┐
              │    按 ID 去重        │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │  四维评分 + 60天过滤  │
              │  文章 Top10 问答Top10 │
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼                               ▼
  ┌──────────────┐               ┌──────────────┐
  │  拉取文章全文  │               │  拉取问答详情  │
  │ cloudscraper │               │ cloudscraper │
  └──────┬───────┘               └──────┬───────┘
         │                               │
  ┌──────▼───────┐               ┌──────▼───────┐
  │ LLM生成评论   │               │ LLM生成回答   │
  │(经验分享风格) │               │(专业回答风格) │
  └──────┬───────┘               └──────┬───────┘
         │                               │
  ┌──────▼───────┐               ┌──────▼───────┐
  │ WordPress    │               │ WordPress    │
  │ 评论API发表   │               │ 评论API发表   │
  └──────────────┘               └──────────────┘
```

### 平台技术要点

| 环节 | 端点 | 方式 | 说明 |
|------|------|------|------|
| 搜索 | `api.woshipm.com/search/result.html` | POST | AJAX API，返回 HTML 片段 |
| 文章页 | `www.woshipm.com/{分类}/{id}.html` | GET | Cloudflare 保护，cloudscraper 穿透 |
| 文章内容 | `og:description` meta 标签 | 正则提取 | ~130 字符摘要，足够 LLM 理解 |
| 评论发表 | `www.woshipm.com/wp-comments-post.php` | POST | WordPress 标准接口 |
| 产品信息 | 产品网站 meta description | GET | 让 LLM 知道产品是什么 |

### 评论生成策略

**三层控制体系**：

```
          ┌─────────────────────────────────┐
          │        System Prompt             │
          │  "像在茶水间跟同行聊天"             │
          │  不要推荐、不要安利                 │
          └───────────────┬─────────────────┘
                          │
          ┌───────────────▼─────────────────┐
          │        产品信息注入               │
          │  抓取 meta description →         │
          │  LLM 知道产品是做什么的            │
          └───────────────┬─────────────────┘
                          │
          ┌───────────────▼─────────────────┐
          │        评论风格随机               │
          │  赞同补充 / 提问讨论 /             │
          │  实战分享 / 案例分析               │
          └───────────────┬─────────────────┘
                          │
          ┌───────────────▼─────────────────┐
          │        禁止词检查                 │
          │  推荐、安利、试试、强烈建议...     │
          └─────────────────────────────────┘
```

**评论风格的多样性**：

| 风格 | 占比 | 模板思路 | 链接融入方式 |
|------|------|----------|-------------|
| 实战分享 | 25% | 讲团队真实经历，踩过的坑 | "后来换了个XX(链接)" |
| 提问讨论 | 25% | 对文中观点有疑问，想深入聊 | "我们试过一种方案(链接)" |
| 赞同补充 | 25% | 共鸣文中观点，补充自己做法 | "我们也是这么做的，当时用XX(链接)" |
| 案例分析 | 25% | 联想到自己的类似项目经历 | "让我想起之前一个项目，后来上了XX(链接)" |

### 评分体系

**四维长尾评分**（高分 = 高曝光机会）：

| 维度 | 权重 | 计算方式 | 设计意图 |
|------|------|----------|----------|
| 曝光机会 | 40 | `40 - 评论数 × (40/20)` | 0评论=满分，20评论=0分 |
| 内容质量 | 30 | `标题长度/60 × 30` | 长标题通常有干货 |
| 作者活跃 | 20 | `20 - 天数 × (20/180)` | 当天=满分，180天=0分 |
| 互动健康 | 10 | `(阅读量/评论数)/500 × 10` | 有人看没人评=你的机会 |

### 反爬策略

| 维度 | 文章评论 | 问答回答 | 设计思路 |
|------|----------|----------|----------|
| 日上限 | 20 | 10 | 每天控制总量 |
| 小时上限 | 8 | 4 | 分散在一天内 |
| 评论间隔 | 60-180s | 90-240s | 模拟人类节奏 |
| 翻页间隔 | 1-3s | — | 搜索不触发频率限制 |
| 关键词间隔 | 10-20s | — | 切换搜索话题 |
| 工作时段 | 8:00-23:00 | — | 正常作息时间 |

---

## 模块二：热点获客发文 v1.2 ✅

RSS 热点（新智元/量子位/Hacker News → 36氪/知乎/V2EX/掘金） → 产品分析 → AI挑选 → LLM生成获客文章 → Pexels封面 → WordPress AJAX API 发布

### 流程设计

```
           输入：产品 URL
                │
     ┌──────────▼──────────┐
     │  抓取产品页面内容     │
     │  浅层抓取→深度抓取    │
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  LLM 结构化分析      │
     │  (产品名/卖点/痛点)  │
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  新智元RSS/量子位    │
     │  Hacker News优先     │
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  AI 挑选最佳热点     │
     │  (PM选题策划视角)    │
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  LLM 生成行业分析文章│
     │  产品经理视角切入    │
     │  纯文本(无Markdown)  │
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  Pexels 封面下载     │
     │  → data/covers/     │
     └──────────┬──────────┘
                │
     ┌──────────▼──────────┐
     │  WordPress AJAX API  │
     │  admin-ajax.php      │
     │  action=add_pending  │
     │  或保存为本地草稿    │
     └─────────────────────┘
```

### 使用

```bash
# 测试模式（不发布）
python3 scripts/woshipm-hotspot-publish.py --product-url "https://example.com" --dry-run

# 正式发布（需在 .env 中配置 WOSHIPM_COOKIE）
python3 scripts/woshipm-hotspot-publish.py --product-url "https://example.com"

# 指定生成数量
python3 scripts/woshipm-hotspot-publish.py --product-url "https://example.com" --max 2
```

### 注意事项

热点获客发文通过 WordPress `admin-ajax.php` 直接发布（与评论区获客使用同样的认证方式）：

- **发布**：`action=add_pending` 提交审核
- **草稿**：`action=add_draft` 保存草稿
- **认证**：Cookie 认证（`WOSHIPM_COOKIE`）
- **技术**：`requests` 直接调用 `admin-ajax.php`，Cookie 认证

---

## LLM 配置

### 模型配置

使用百度千帆 Coding Plan API（OpenAI 兼容接口），配置在 `config/llm.json`：

```json
{
  "provider": "baiduqianfancodingplan",
  "api_key": "bce-v3/xxx",
  "model": "qianfan-code-latest"
}
```

也支持 `deepseek`、`sensenova` 等 provider。模板文件 `config/llm.template.json` 复制为 `llm.json` 后填入实际 API Key。

---

## 安装依赖

```bash
pip install cloudscraper requests beautifulsoup4
```

## 配置

```bash
# .env 文件（仅保留 Cookie）
WOSHIPM_COOKIE="你的登录Cookie"
```

Cookie 获取方式：登录 woshipm.com → F12 → Application → Cookies → 复制所有值。

## CLI 命令

```bash
# ── 评论区获客 ──
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" --dry-run

python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" \
  --max-comments 10 --max-answers 3

# ── 独立搜索 ──
python3 scripts/woshipm_search.py --keyword "产品经理" --max-pages 3

# ── 热点获客发文 ──
python3 scripts/woshipm-hotspot-publish.py --product-url "https://your-product.com" --dry-run
python3 scripts/woshipm-hotspot-publish.py --product-url "https://your-product.com"
```

## 文件结构

```
woshipm-publisher/
├── SKILL.md                         ← 本文
├── README.md                        ← 用户使用指南
├── _meta.json                       ← 技能元数据
├── .env                             ← Cookie 配置
├── woshipm_acquisition_config.json  ← 获客策略配置
│
├── config/                          ← LLM 配置
│   ├── llm.json                     ← provider/api_key/model
│   └── llm.template.json            ← 模板
│
├── scripts/                         ← Python 脚本
│   ├── woshipm_acquisition.py       ← 评论区获客
│   ├── woshipm_search.py            ← 独立搜索
│   ├── woshipm-hotspot-publish.py   ← ★ 热点获客发文
│   └── zhihu_llm.py                 ← LLM 调用封装
│
├── templates/                       ← LLM 提示词模板
│   ├── product-analysis-prompt.md   ← ★ 产品分析模板
│   └── hotspot-acquisition-prompt.md ← ★ 获客文章模板
│
├── output/                          ← 生成文章预览
└── data/                            ← 运行时数据
    ├── covers/                      ← Pexels 封面图本地缓存
    ├── commented-history.json
    └── answered-history.json
```
