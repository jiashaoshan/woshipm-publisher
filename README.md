# woshipm-publisher

人人都是产品经理(woshipm.com) 全栈运营技能：AI 驱动的评论区获客 + 文章发布。

[![version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/jiashaoshan/woshipm-publisher)
[![python](https://img.shields.io/badge/python-3.8+-green)](https://www.python.org/)

## 功能

### 评论区获客 ✅

输入一个产品链接，自动完成：

1. **理解产品** — 抓取产品网站 meta 信息，知道产品是做什么的
2. **生成关键词** — LLM 产出 8 个搜索关键词，覆盖不同搜索意图
3. **搜索文章** — 在 woshipm 搜索文章(tab=0) 和问答(tab=2)，各取前5页
4. **智能筛选** — 四维评分：曝光机会 + 内容质量 + 作者活跃 + 互动健康，优先评论少但有干货的文章
5. **生成评论** — LLM 阅读文章全文，结合产品信息，生成自然的经验分享评论（不是硬广）
6. **自动发表** — 通过 WordPress 评论接口自动发表

### 文章发布 🚧

(规划中)

## 快速开始

### 1. 安装

```bash
pip install cloudscraper
```

### 2. 配置

```bash
cp .env woshipm.env
```

编辑 `woshipm.env`，填入你的 Cookie（登录 woshipm.com → F12 → Application → Cookies → 复制全部值）。

### 3. 运行

```bash
# 测试模式（不发表评论，查看全流程）
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" --dry-run

# 正式运行（发1条评论试试水）
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" \
  --max-comments 1

# 正式运行（批量）
python3 scripts/woshipm_acquisition.py auto \
  --product-url "https://your-product.com" \
  --max-comments 10 --max-answers 3

# 独立搜索
python3 scripts/woshipm_search.py --keyword "产品经理"
```

## 评论示例

输入产品 [智信AI中转平台](https://ai.interwestinfo.com/)（AI 模型聚合与分发网关），LLM 对文章"别再迷信沉重的 AI 壳子了：从 DeepSeek-Reasonix 看 B 端真正的 ROI 刺客"生成的评论：

> 确实被"沉重的 AI 壳子"这个说法戳到了。我们之前接DeepSeek，自己搞了一套封装转发，结果光维护不同模型的输入输出规范就耗掉了两个人周，后来换了个聚合网关（https://ai.interwestinfo.com/）统一成OpenAI接口格式，省去了一大堆兼容代码。ROI的"刺客"根本不是模型本身，而是那些没必要的集成复杂度。

特点：
- 先回应文章观点（"被戳到了"）
- 讲真实经历（"我们之前...耗掉了两个人周"）
- 链接作为经历的注脚，不是推销

## 设计理念

### 问题：传统"评论区获客"为什么效果差？

| 常见做法 | 为什么不好 |
|----------|-----------|
| 批量发"好文章学习了" | 无价值，无人理会 |
| 硬塞产品链接 | 一眼广告，被举报 |
| LLM 盲写评论 | 编造内容，必穿帮 |
| 追着热门文章评论 | 评论区拥挤，评论秒沉 |
| 不知道产品是什么 | LLM 瞎猜产品功能 |

### 解法：本技能的四个核心设计

1. **先理解产品，再生成评论** — 抓取产品页面的 meta description，让 LLM 知道产品到底是什么
2. **先拉取文章全文，再写评论** — LLM 基于真实内容生成，不是盲写
3. **找长尾文章，不是追热门** — 评分体系偏爱"有人看但没人评"的文章，你的评论才会被看到
4. **经验分享风格，不是推销** — 系统提示词要求"像茶水间聊天"，禁止"推荐"、"安利"等推销词

## 配置说明

```json
{
  "filters": {
    "search_pages": 5,        // 每关键词搜索页数
    "search_sort_type": 1,     // 0=综合 1=时间
    "max_days_old": 60,        // 只评论60天内的文章
    "top_n": 10                // 评分后取Top N
  },
  "anti_crawl": {
    "daily": { "max_comments": 20, "max_answers": 10 },
    "hourly": { "max_comments": 8, "max_answers": 4 },
    "delays": {
      "between_comments": { "min": 60, "max": 180 }
    }
  },
  "transparent_mode": true,    // true=经验分享含链接, false=纯讨论不推广
  "search_tabs": {
    "article": 0,              // tab=0 文章
    "qa": 2                    // tab=2 问答
  }
}
```

## 技术栈

- **搜索**: `api.woshipm.com` AJAX 端点
- **页面抓取**: `cloudscraper` 穿透 Cloudflare 保护
- **内容提取**: `og:description` meta + HTML 段落解析
- **评论发表**: WordPress 标准 `wp-comments-post.php`
- **LLM**: DeepSeek API（通过共享 `zhihu_llm.py` 模块）

## 目录结构

```
woshipm-publisher/
├── SKILL.md                         # 技术设计与架构文档
├── README.md                        # 本文件
├── _meta.json                       # 技能元数据
├── .env                             # Cookie + LLM 密钥
├── woshipm_acquisition_config.json  # 获客策略配置
├── scripts/
│   ├── woshipm_acquisition.py       # 获客主脚本
│   └── woshipm_search.py            # 独立搜索工具
├── data/                            # 运行时数据
└── templates/                       # 发布模板 (待)
```
