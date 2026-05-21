# woshipm-publisher

人人都是产品经理(woshipm.com) 全栈运营技能。

## 功能

### 模块一：评论区获客 v1.0

全自动管道：

```
产品链接 → LLM生成关键词(8个) → 搜索文章(tab=0)+问答(tab=2)
→ 四维评分筛选(各Top N) → 拉取全文 → LLM生成评论/回答 → 自动发表
```

#### 搜索

- **文章 (tab=0)**: 搜索 + 时间排序 + 取前5页
- **问答 (tab=2)**: 搜索 + 时间排序 + 取前5页
- 接口: `POST https://api.woshipm.com/search/result.html`

#### 内容获取

- 页面: `https://www.woshipm.com/active/{id}.html`
- 网站有 Cloudflare 保护，使用 cloudscraper 穿透
- 提取文章正文用于 LLM 生成评论

#### 评论发表

- 平台使用 WordPress，评论接口: `POST https://www.woshipm.com/wp-comments-post.php`
- 字段: `comment`, `comment_post_ID`, `comment_parent`
- 需要登录 Cookie

#### 四维评分 (长尾优先)

| 维度 | 权重 | 说明 |
|------|------|------|
| 曝光机会 | 40 | 评论越少分越高 |
| 内容质量 | 30 | 标题/正文越长越有干货 |
| 时效性 | 20 | 越新分越高 |
| 互动健康度 | 10 | 阅读多评论少=机会 |

#### 透明/价值先行模式

- `transparent_mode=true`: 先提供价值，产品自然提及
- `transparent_mode=false`: 纯产品讨论，不提产品

### 模块二：发文功能 🚧

(待开发)

## 安装

```bash
# 安装依赖
pip install cloudscraper

# 配置 Cookie
cp .env woshipm.env
# 编辑 woshipm.env，填入你的 WOSHIPM_COOKIE
```

## 使用

```bash
# 全自动获客（DRY-RUN 测试）
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" --dry-run

# 全自动获客（正式运行）
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" \
  --max-comments 10 --max-answers 3

# 单独搜索
python3 scripts/woshipm_acquisition.py search --keyword "产品经理"

# 单独评论
python3 scripts/woshipm_acquisition.py comment --article-id 6397495
```

## 配置

`woshipm_acquisition_config.json`:

- `keywords`: 种子关键词池
- `filters.search_pages`: 每关键词搜索页数
- `filters.search_sort_type`: 1=时间排序
- `search_tabs.article`: 0, `search_tabs.qa`: 2
- `anti_crawl`: 速率限制

## 文件结构

```
woshipm-publisher/
├── SKILL.md
├── .env                          # Cookie 配置
├── woshipm_acquisition_config.json
├── scripts/
│   ├── woshipm_acquisition.py    # 获客主脚本
│   └── woshipm_search.py         # 独立搜索工具
├── data/
│   ├── commented-history.json    # 评论去重记录
│   └── answered-history.json     # 回答去重记录
└── templates/                    # 发布模板(待)
```
