#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人人都是产品经理(woshipm) 评论区获客脚本 v1.0
功能:
  1. 搜索文章(tab=0)和问答(tab=2) → 四维评分筛选 → 拉取全文
  2. LLM生成评论(文章)/回答(问答) → 自动发表

平台要点:
  - 搜索: POST api.woshipm.com/search/result.html (AJAX)
  - 文章: www.woshipm.com/active/{id}.html (Cloudflare保护, cloudscraper穿透)
  - 评论: POST www.woshipm.com/wp-comments-post.php (WordPress标准)
  - 问答: www.woshipm.com/questions/{id}.html
"""

import sys
import os
import json
import re
import html as html_mod
import argparse
import urllib.request
import urllib.error
import urllib.parse
import time
import random
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path

# ─── 尝试导入 cloudscraper ────────────────────────────────
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False
    print("警告: cloudscraper 未安装，无法访问文章详情页。pip install cloudscraper")

# ─── 模块路径 ─────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

# 尝试导入共享 LLM 模块
_LLM_MODULE = None
_LLM_SEARCH_PATHS = [
    os.path.join(os.path.dirname(SKILL_ROOT), "juejin-publisher", "scripts", "zhihu_llm.py"),
    os.path.join(SCRIPT_DIR, "zhihu_llm.py"),
]
_LLM_MODULE_PATH = None
for p in _LLM_SEARCH_PATHS:
    if os.path.exists(p):
        _LLM_MODULE_PATH = p
        break
if _LLM_MODULE_PATH:
    import importlib.util
    spec = importlib.util.spec_from_file_location("zhihu_llm", _LLM_MODULE_PATH)
    _LLM_MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_LLM_MODULE)
    call_llm = _LLM_MODULE.call_llm
    call_llm_json = _LLM_MODULE.call_llm_json
else:
    call_llm = None
    call_llm_json = None

# ─── 路径配置 ─────────────────────────────────────────────
CONFIG_FILE = os.path.join(SKILL_ROOT, ".env")
ACQUISITION_CONFIG = os.path.join(SKILL_ROOT, "woshipm_acquisition_config.json")
DATA_DIR = os.path.join(SKILL_ROOT, "data")
COMMENTED_FILE = os.path.join(DATA_DIR, "commented-history.json")
ANSWERED_FILE = os.path.join(DATA_DIR, "answered-history.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ─── 常量 ─────────────────────────────────────────────────
SEARCH_URL = "https://api.woshipm.com/search/result.html"
ARTICLE_URL_TPL = "https://www.woshipm.com/active/{article_id}.html"
COMMENT_URL = "https://www.woshipm.com/wp-comments-post.php"

HEADERS_SEARCH = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://api.woshipm.com/search/list.html",
}

# ─── 日志配置 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(SKILL_ROOT, "woshipm_acquisition.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
#  配置加载
# ═══════════════════════════════════════════════════════════

def load_env() -> dict:
    """加载 .env 配置"""
    config = {}
    env_files = [CONFIG_FILE, os.path.join(SKILL_ROOT, "woshipm.env")]

    for env_file in env_files:
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    val = val.strip().strip('"').strip("'")
                    config[key.strip()] = val

    for env_key in ("WOSHIPM_COOKIE",):
        env_val = os.environ.get(env_key, "")
        if env_val:
            config[env_key] = env_val

    return config


def load_acquisition_config() -> dict:
    """加载获客配置（带深度合并）"""
    default = {
        "keywords": ["产品经理", "需求分析", "AI产品"],
        "scoring": {
            "exposure_weight": 40, "quality_weight": 30,
            "activity_weight": 20, "health_weight": 10,
        },
        "filters": {
            "min_view_count": 0, "min_comment_count": 0,
            "max_days_old": 60, "top_n": 10,
            "search_pages": 5, "search_sort_type": 1,
        },
        "transparent_mode": True,
        "anti_crawl": {
            "work_hours": {"start": 8, "end": 23},
            "daily": {"max_comments": 20, "max_answers": 10},
            "hourly": {"max_comments": 8, "max_answers": 4},
            "delays": {
                "between_comments": {"min": 60, "max": 180},
                "between_answers": {"min": 90, "max": 240},
                "between_searches": {"min": 3, "max": 8},
                "between_keywords": {"min": 10, "max": 20},
                "between_pages": {"min": 1, "max": 3},
            },
            "retry": {"max_attempts": 3, "base_delay": 20},
        },
        "search_tabs": {"article": 0, "qa": 2},
    }
    user_config = {}
    if os.path.exists(ACQUISITION_CONFIG):
        try:
            with open(ACQUISITION_CONFIG, "r", encoding="utf-8") as f:
                user_config = json.load(f)
        except Exception:
            pass
    for key in default:
        if key not in user_config:
            user_config[key] = default[key]
        elif isinstance(default[key], dict) and isinstance(user_config[key], dict):
            for subkey in default[key]:
                if subkey not in user_config[key]:
                    user_config[key][subkey] = default[key][subkey]
    return user_config


def load_history(path: str) -> list:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(path: str, records: list):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"保存历史记录失败: {e}")


# ═══════════════════════════════════════════════════════════
#  cloudscraper 会话管理
# ═══════════════════════════════════════════════════════════

def get_scraper(cookie: str = "") -> cloudscraper.CloudScraper:
    """获取新的 cloudscraper 会话"""
    if not HAS_CLOUDSCRAPER:
        return None
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
        delay=15,
    )
    scraper.headers.update({
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.baidu.com/",
        "Cache-Control": "no-cache",
    })
    scraper.cookies.clear()
    return scraper


# ═══════════════════════════════════════════════════════════
#  搜索 API (api.woshipm.com)
# ═══════════════════════════════════════════════════════════

def search_page(keyword: str, page: int = 1, tab: int = 0,
                sort_type: int = 1) -> Tuple[List[dict], int]:
    """
    请求单页搜索结果

    Args:
        keyword: 搜索关键词
        page: 页码
        tab: 0=文章, 2=问答
        sort_type: 0=综合, 1=时间

    Returns:
        (articles, total_count)
    """
    data = f"key={urllib.parse.quote(keyword)}&tab={tab}&page={page}&idSearch=&sortType={sort_type}"
    req = urllib.request.Request(SEARCH_URL, data=data.encode("utf-8"), headers=HEADERS_SEARCH)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"搜索请求失败: {e}")
        return [], 0

    articles = []
    total_count = 0

    # 总数
    count_match = re.search(r"(\d+)", html)
    if count_match:
        total_count = int(count_match.group(1))

    # 提取文章
    items = re.split(r'<div class="course--item"', html)[1:]

    for item in items:
        id_match = re.search(r'id\s*=\s*(\d+)', item)
        if not id_match or id_match.group(1) == "0":
            continue
        article_id = id_match.group(1)

        title_match = re.search(r'class="title"[^>]*>(.*?)</a>', item, re.DOTALL)
        if not title_match:
            continue
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        if not title:
            continue

        # 作者+日期
        author_match = re.search(r'class="pull-left">(.*?)</span>', item)
        author_info = html_mod.unescape(author_match.group(1).strip()) if author_match else ""
        author, date_str = "", ""
        if "·" in author_info:
            parts = author_info.split("·", 1)
            author = parts[0].strip()
            date_str = parts[1].strip() if len(parts) > 1 else ""

        # 阅读量
        views_match = re.search(r'阅读\s*([\d.kw万]+)', html_mod.unescape(item))
        views = views_match.group(1) if views_match else ""

        # 评论数
        comment_count = 0
        cc_match = re.search(r'(\d+)\s*评论', item)
        if cc_match:
            comment_count = int(cc_match.group(1))

        url = ARTICLE_URL_TPL.format(article_id=article_id)

        articles.append({
            "article_id": article_id,
            "title": title,
            "url": url,
            "author": author,
            "date": date_str,
            "views": views,
            "comment_count": comment_count,
            "keyword": keyword,
            "tab": tab,
        })

    return articles, total_count


def search_all_pages(keyword: str, tab: int = 0, sort_type: int = 1,
                     max_pages: int = 5, delays: dict = None) -> List[dict]:
    """搜索多页并汇总"""
    all_articles = []
    page = 1

    while page <= max_pages:
        logger.info(f"  搜索[{keyword}] tab={tab} 第{page}页...")
        articles, total = search_page(keyword, page, tab, sort_type)

        if page == 1:
            logger.info(f"  共 {total} 条结果")

        if not articles:
            break

        all_articles.extend(articles)

        if len(articles) < 10:
            break

        page += 1
        if delays:
            wait_random(delays.get("between_pages", {}).get("min", 1),
                        delays.get("between_pages", {}).get("max", 3),
                        "翻页间隔")

    return all_articles


# ═══════════════════════════════════════════════════════════
#  文章内容抓取 (www.woshipm.com, cloudscraper穿透)
# ═══════════════════════════════════════════════════════════

def fetch_article_content(article_id: str, cookie: str = "") -> str:
    """抓取文章内容（优先 og:description，兜底全文段落提取）"""
    if not HAS_CLOUDSCRAPER:
        logger.warning("cloudscraper 不可用，无法拉取文章内容")
        return ""

    content = ""
    try:
        scraper = get_scraper(cookie)
        if scraper is None:
            return ""
        url = ARTICLE_URL_TPL.format(article_id=article_id)
        resp = scraper.get(url, timeout=25, allow_redirects=True)

        if resp.status_code != 200:
            logger.warning(f"拉取文章失败: HTTP {resp.status_code} ({url})")
            return ""

        html = resp.text

        # 方案1: og:description (足够LLM理解文章核心)
        desc_m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        if desc_m:
            content = html_mod.unescape(desc_m.group(1)).strip()

        # 方案2: 如果 og:description 不够，尝试全文段落
        if not content or len(content) < 100:
            # 提取所有有实际内容的 <p> 标签
            paragraphs = re.findall(r'<p[^>]*?>(.*?)</p>', html, re.DOTALL)
            body = []
            for p in paragraphs:
                text = re.sub(r'<[^>]+>', '', p).strip()
                text = re.sub(r'\s+', ' ', text)
                # 过滤掉页头/页脚/JS等内容
                if (len(text) > 30
                        and 'function' not in text
                        and 'cookie' not in text.lower()
                        and '.css' not in text
                        and '.js' not in text):
                    body.append(text)
            if body:
                content = '\n\n'.join(body[:20])

        if content and len(content) > 30:
            logger.info(f"✓ 拉取文章内容: {article_id} ({len(content)} 字符)")
            return content

        logger.warning(f"拉取文章内容为空: {article_id}")
        return ""

    except Exception as e:
        logger.warning(f"拉取文章异常 ({article_id}): {e}")
        return ""


# ═══════════════════════════════════════════════════════════
#  反爬策略
# ═══════════════════════════════════════════════════════════

def is_work_hours(config: dict) -> bool:
    now = datetime.now()
    wh = config.get("anti_crawl", {}).get("work_hours", {})
    if wh.get("start", 8) <= now.hour < wh.get("end", 23):
        return True
    logger.warning(f"当前时间 {now.hour}:00 不在工作时段，跳过")
    return False


def wait_random(min_sec: float = 5, max_sec: float = 15, reason: str = "操作间隔"):
    delay = random.uniform(min_sec, max_sec)
    logger.info(f"⏳ {reason}，等待 {int(delay)}s...")
    time.sleep(delay)


def check_rate_limits(history: list, label: str, daily_max: int, hourly_max: int) -> Tuple[bool, str]:
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    hour_str = now.strftime("%Y-%m-%d %H:00")
    today_count = sum(1 for r in history if r.get("timestamp", "").startswith(today_str))
    hour_count = sum(1 for r in history if r.get("timestamp", "").startswith(hour_str))
    if today_count >= daily_max:
        return False, f"今日{label} {today_count}/{daily_max}，已达上限"
    if hour_count >= hourly_max:
        return False, f"本小时{label} {hour_count}/{hourly_max}，已达上限"
    return True, f"余量: 今日{daily_max - today_count}，本小时{hourly_max - hour_count}"


# ═══════════════════════════════════════════════════════════
#  评分（长尾优先）
# ═══════════════════════════════════════════════════════════

def score_article(article: dict, config: dict) -> float:
    """四维评分：优先评论少、质量高、时效新、互动健康的文章"""
    scoring = config.get("scoring", {})

    # 曝光机会（40分）：评论越少越容易被看到
    ew = scoring.get("exposure_weight", 40)
    cc = article.get("comment_count", 0)
    exposure = max(0, ew - cc * (ew / 20))

    # 内容质量（30分）：标题长度代理（后续可用正文长度）
    qw = scoring.get("quality_weight", 30)
    title_len = len(article.get("title", ""))
    quality = min(title_len / 60 * qw, qw)

    # 时效性（20分）：优先近期文章
    aw = scoring.get("activity_weight", 20)
    date_str = article.get("date", "")
    days_old = 365
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days_old = (datetime.now() - dt).days
    except Exception:
        pass
    activity = max(0, aw - days_old * (aw / 180))

    # 互动健康度（10分）
    hw = scoring.get("health_weight", 10)
    views_str = article.get("views", "0")
    views = 0
    try:
        views_str = views_str.replace("k", "000").replace("w", "0000").replace("万", "0000")
        views = int(float(views_str))
    except Exception:
        pass
    health = min((views / max(cc, 1)) / 500 * hw, hw)

    return exposure + quality + activity + health


def score_and_filter(articles: List[dict], config: dict) -> List[dict]:
    """评分 + 过滤 + 排序 Top N"""
    filters = config.get("filters", {})
    top_n = filters.get("top_n", 10)
    max_days = filters.get("max_days_old", 60)

    scored = []
    for a in articles:
        # 时间过滤
        date_str = a.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if (datetime.now() - dt).days > max_days:
                continue
        except Exception:
            pass

        a["score"] = score_article(a, config)
        scored.append(a)

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    logger.info(f"✓ 评分筛选: {len(articles)}→Top{len(top)}")
    for i, a in enumerate(top[:5], 1):
        logger.info(f"  [{i}] {a['title'][:40]:<42} score={a['score']:.1f}")

    return top


# ═══════════════════════════════════════════════════════════
#  关键词生成
# ═══════════════════════════════════════════════════════════

def generate_keywords(product_url: str = "", seed_keywords: list = None) -> list:
    """LLM 生成搜索关键词"""
    if call_llm_json is None:
        return (seed_keywords or [])[:6]

    try:
        prompt = f"""根据以下产品信息，生成8个woshipm(人人都是产品经理)搜索关键词。
覆盖：用户痛点、产品设计、产品运营、竞品分析、行业趋势。

产品信息：{product_url or "AI产品相关服务"}

要求：
- 每个关键词简洁（2-8字），贴合产品经理社区
- 宽泛+精准搭配：3个宽泛词(覆盖大方向) + 5个精准词(切具体场景)
- 返回JSON：{{"keywords": ["词1","词2",...], "reasoning": "说明"}}"""

        result = call_llm_json(
            system_prompt="你是一位产品经理社区的内容策略分析师。",
            user_prompt=prompt, temperature=0.7, max_tokens=1024,
        )
        keywords = result.get("keywords", [])
        if isinstance(keywords, list) and len(keywords) >= 3:
            logger.info(f"✓ LLM 生成 {len(keywords)} 个关键词")
            return keywords[:10]
    except Exception as e:
        logger.warning(f"LLM 关键词生成失败: {e}")

    return (seed_keywords or [])[:6]


# ═══════════════════════════════════════════════════════════
#  评论/回答生成
# ═══════════════════════════════════════════════════════════

def generate_comment(article: dict, product_url: str = "", cookie: str = "",
                     transparent: bool = True) -> str:
    """LLM生成评论（基于文章全文）"""
    if call_llm is None:
        return generate_fallback_comment(article)

    try:
        # 拉取全文
        full_content = ""
        if cookie:
            full_content = fetch_article_content(article["article_id"], cookie)

        body = full_content[:2500] if full_content else article.get("title", "")

        if transparent:
            system_prompt = (
                "你是一位产品经理，在人人都是产品经理社区认真读了一篇文章后留下评论。\n"
                "原则：\n"
                "1. 先提供价值——基于文章具体内容补充产品观点或实践经验\n"
                "2. 必须引用文中至少1个具体观点\n"
                "3. 如果产品与文章自然相关，可轻提一句\n"
                "4. 口语化、专业、真诚，像同行交流"
            )
        else:
            system_prompt = (
                "你是一位产品经理，在社区认真读了一篇文章后参与讨论。\n"
                "1. 必须引用文中的具体观点\n"
                "2. 分享真实的产品实践经验或思考\n"
                "3. 纯技术/产品讨论，不提任何产品名或链接"
            )

        comment_type = random.choice(["赞同补充", "提问讨论", "实战分享", "案例分析"])
        style_hints = {
            "赞同补充": "赞同文中某个观点，补充自己相关的产品实践经验。",
            "提问讨论": "对文中的产品决策或方法论提出有深度的疑问。",
            "实战分享": "分享自己在该产品方向的真实实践经验和教训。",
            "案例分析": "结合文中的案例引申自己的类似经历和思考。",
        }

        user_prompt = f"""
你在人人都是产品经理社区读了一篇文章，打算发表评论。

## 文章内容
标题：{article['title']}
正文（节选）：
{body}

## 评论风格：{comment_type}
{style_hints.get(comment_type, '')}

## 要求
- 字数：80-200字
- 必须引用文中至少1个具体观点
- 口语化但专业，像真实产品经理的讨论"""

        if transparent and product_url:
            user_prompt += f"\n- 若内容自然相关可轻提：{product_url}，不相关则不提"

        user_prompt += "\n\n直接返回评论文本。"

        comment = call_llm(
            system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=0.7, max_tokens=400,
        ).strip()

        if len(comment) > 300:
            comment = comment[:297] + "..."

        logger.info(f"✓ LLM 生成评论 ({comment_type}): {comment[:80]}...")
        return comment

    except Exception as e:
        logger.warning(f"LLM 评论生成失败: {e}")
        return generate_fallback_comment(article)


def generate_answer(article: dict, product_url: str = "", cookie: str = "",
                    transparent: bool = True) -> str:
    """LLM生成问答回答"""
    if call_llm is None:
        return generate_fallback_comment(article)

    try:
        full_content = ""
        if cookie:
            full_content = fetch_article_content(article["article_id"], cookie)

        body = full_content[:2000] if full_content else article.get("title", "")

        system_prompt = (
            "你是一位资深产品经理，在社区认真回答一个问题。\n"
            "原则：\n"
            "1. 先直接回答问题，给出明确的观点和建议\n"
            "2. 如果知道相关产品解决方案，可以在回答末尾自然地提及\n"
            "3. 专业、真诚、有结构，像一位乐于分享的同行\n"
            "4. 不要编造经验，不确定的地方诚实说明"
        )

        user_prompt = f"""
你在人人都是产品经理社区看到一个产品相关问题，打算认真回答。

## 问题
{article['title']}

## 问题详情
{body}

## 回答要求
- 200-500字，有结构（如：我的看法 → 具体建议 → 注意事项）
- 直接回答问题核心
- 可分享真实经验
- 口语化但专业"""

        if transparent and product_url:
            user_prompt += f"\n- 若相关可自然提及：{product_url}，不需要时完全别提"

        user_prompt += "\n\n直接返回回答文本。"

        answer = call_llm(
            system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=0.7, max_tokens=600,
        ).strip()

        if len(answer) > 500:
            answer = answer[:497] + "..."

        logger.info(f"✓ LLM 生成回答: {answer[:80]}...")
        return answer

    except Exception as e:
        logger.warning(f"LLM 回答生成失败: {e}")
        return generate_fallback_comment(article)


def generate_fallback_comment(article: dict) -> str:
    """兜底评论"""
    templates = [
        "感谢分享！{topic}这块确实值得深入探讨，最近也在关注这个方向。",
        "文章分析得很到位，{topic}的实践经验很宝贵。",
        "学到了，{topic}的思路很清晰，正好最近在调研这个方向。",
    ]
    topic = (article.get("title", "这个话题") or "这个话题")[:15]
    return random.choice(templates).format(topic=topic)


# ═══════════════════════════════════════════════════════════
#  评论/回答发表器
# ═══════════════════════════════════════════════════════════

class Commenter:
    """评论/回答发表器"""

    def __init__(self, cookie: str, config: dict, product_url: str = "",
                 history_file: str = COMMENTED_FILE, label: str = "评论"):
        self.cookie = cookie
        self.config = config
        self.product_url = product_url
        self.transparent = config.get("transparent_mode", True)
        self.label = label
        self.history_file = history_file
        self.history = load_history(history_file)
        self.dry_run = False

    def _is_processed(self, article_id: str) -> Tuple[bool, str]:
        for r in self.history:
            if r.get("article_id") == article_id:
                return True, "已处理过"
        return False, ""

    def post_with_scraper(self, article_id: str, content: str) -> bool:
        """通过 cloudscraper 发表评论（WordPress wp-comments-post.php）"""
        if not HAS_CLOUDSCRAPER:
            logger.error("需要 cloudscraper 才能发表评论")
            return False

        try:
            scraper = get_scraper(self.cookie)
            if scraper is None:
                logger.error("需要 cloudscraper 才能发表评论")
                return False

            # WordPress 标准评论表单字段
            data = {
                "comment": content,
                "comment_post_ID": article_id,
                "comment_parent": "0",
                "submit": "发布",
            }

            # 添加 cookie
            if self.cookie and "=" in self.cookie:
                for item in self.cookie.split(";"):
                    item = item.strip()
                    if "=" in item:
                        k, v = item.split("=", 1)
                        scraper.cookies.set(k.strip(), v.strip())

            resp = scraper.post(COMMENT_URL, data=data, timeout=20,
                                headers={"Referer": ARTICLE_URL_TPL.format(article_id=article_id)})

            if resp.status_code in (200, 302):
                return True

            logger.warning(f"评论发表异常: HTTP {resp.status_code}")
            return False

        except Exception as e:
            logger.error(f"评论发表异常: {e}")
            return False

    def process(self, article: dict, keyword: str = "") -> Tuple[bool, str]:
        """处理单篇文章/问答：生成内容 + 发表"""
        if self.dry_run:
            logger.info(f"[DRY-RUN] 模拟{self.label}: {article['title'][:40]}...")
            return True, "dry-run"

        # 去重
        is_dup, reason = self._is_processed(article["article_id"])
        if is_dup:
            logger.info(f"  跳过（{reason}）: {article['title'][:40]}...")
            return False, f"skip:{reason}"

        # 反爬
        anti = self.config.get("anti_crawl", {})
        dkey = "max_comments" if self.label == "评论" else "max_answers"
        hkey = "max_comments" if self.label == "评论" else "max_answers"
        ok, msg = check_rate_limits(self.history, self.label,
                                     anti.get("daily", {}).get(dkey, 10),
                                     anti.get("hourly", {}).get(hkey, 5))
        if not ok:
            return False, f"rate_limit:{msg}"

        # LLM 生成
        if self.label == "评论":
            text = generate_comment(article, self.product_url, self.cookie, self.transparent)
        else:
            text = generate_answer(article, self.product_url, self.cookie, self.transparent)

        # 发表
        logger.info(f"⎿ 发表{self.label}: {article['title'][:40]}...")
        success = self.post_with_scraper(article["article_id"], text)

        if success:
            record = {
                "article_id": article["article_id"],
                "title": article.get("title", ""),
                "content": text[:200],
                "keyword": keyword,
                "timestamp": datetime.now().isoformat(),
                "type": self.label,
            }
            self.history.append(record)
            save_history(self.history_file, self.history)
            logger.info(f"✓ {self.label}成功: {article['title'][:40]}...")
            return True, "success"
        else:
            return False, "post_failed"


# ═══════════════════════════════════════════════════════════
#  全自动获客管道
# ═══════════════════════════════════════════════════════════

class AutoAcquisition:
    """全自动获客管道"""

    def __init__(self, cookie: str, config: dict, product_url: str = ""):
        self.cookie = cookie
        self.config = config
        self.product_url = product_url
        self.article_commenter = Commenter(
            cookie, config, product_url, COMMENTED_FILE, "评论")
        self.qa_answerer = Commenter(
            cookie, config, product_url, ANSWERED_FILE, "回答")

    def run(self, max_comments: int = 5, max_answers: int = 2,
            dry_run: bool = False):
        """执行全自动获客"""
        self.dry_run = dry_run
        self.article_commenter.dry_run = dry_run
        self.qa_answerer.dry_run = dry_run

        logger.info("=" * 60)
        logger.info("🎯 人人都是产品经理 评论区获客启动")
        logger.info(f"  产品: {self.product_url or '未指定'}")
        logger.info(f"  模式: {'DRY-RUN' if dry_run else 'LIVE'}")
        logger.info("=" * 60)

        if not dry_run and not is_work_hours(self.config):
            return {"success": False, "reason": "not_work_hours"}

        # 关键词
        seed_kw = self.config.get("keywords", [])
        keywords = generate_keywords(self.product_url, seed_kw)
        logger.info(f"✓ {len(keywords)} 个关键词: {keywords}")

        filters = self.config.get("filters", {})
        search_pages = filters.get("search_pages", 5)
        sort_type = filters.get("search_sort_type", 1)
        tabs = self.config.get("search_tabs", {"article": 0, "qa": 2})
        anti = self.config.get("anti_crawl", {})
        delays = anti.get("delays", {})

        comments_done = 0
        answers_done = 0
        all_articles = []
        debug_info = []

        # 搜索文章 (tab=0)
        logger.info("\n📄 搜索文章 (tab=0)...")
        for kw in keywords:
            if comments_done >= max_comments:
                break
            articles = search_all_pages(kw, tabs["article"], sort_type, search_pages, delays)
            all_articles.extend([a for a in articles if a["tab"] == 0])

        # 搜索问答 (tab=2)
        logger.info("\n❓ 搜索问答 (tab=2)...")
        for kw in keywords:
            if answers_done >= max_answers:
                break
            qa_items = search_all_pages(kw, tabs["qa"], sort_type, search_pages, delays)
            all_articles.extend([a for a in qa_items if a["tab"] == 2])

        logger.info(f"✓ 共搜索到 {len(all_articles)} 条内容（去重前）")

        # 按 article_id 去重
        seen_ids = set()
        unique_articles = []
        for a in all_articles:
            aid = a.get("article_id")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                unique_articles.append(a)
        all_articles = unique_articles
        logger.info(f"✓ 去重后 {len(all_articles)} 条内容")

        # 分类
        articles_only = [a for a in all_articles if a["tab"] == 0]
        qa_only = [a for a in all_articles if a["tab"] == 2]

        # 评分筛选
        top_articles = score_and_filter(articles_only, self.config)
        top_qa = score_and_filter(qa_only, self.config)

        # 评论文章
        for article in top_articles:
            if comments_done >= max_comments:
                break
            ok, msg = self.article_commenter.process(article, article.get("keyword", ""))
            if ok:
                comments_done += 1
                debug_info.append({"action": "comment", "title": article["title"], "status": msg})
                d = delays.get("between_comments", {"min": 60, "max": 180})
                wait_random(d["min"], d["max"], "评论间隔")
            else:
                debug_info.append({"action": "comment", "title": article["title"], "status": f"fail:{msg}"})

        # 回答问答
        for qa in top_qa:
            if answers_done >= max_answers:
                break
            ok, msg = self.qa_answerer.process(qa, qa.get("keyword", ""))
            if ok:
                answers_done += 1
                debug_info.append({"action": "answer", "title": qa["title"], "status": msg})
                d = delays.get("between_answers", {"min": 90, "max": 240})
                wait_random(d["min"], d["max"], "回答间隔")
            else:
                debug_info.append({"action": "answer", "title": qa["title"], "status": f"fail:{msg}"})

        # 汇总
        logger.info("\n" + "=" * 60)
        logger.info("✅ 执行完成")
        logger.info(f"  搜索关键词: {len(keywords)} 个")
        logger.info(f"  找到内容:   {len(all_articles)} 条")
        logger.info(f"  评论成功:   {comments_done} 条")
        logger.info(f"  回答成功:   {answers_done} 条")
        logger.info(f"  模式:       {'DRY-RUN' if dry_run else 'LIVE'}")

        return {
            "success": True,
            "stats": {
                "keywords": len(keywords),
                "total_found": len(all_articles),
                "comments": comments_done,
                "answers": answers_done,
                "dry_run": dry_run,
            },
            "details": debug_info,
        }


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="人人都是产品经理 评论区获客脚本 v1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 全自动获客
  python3 woshipm_acquisition.py auto --product-url "https://example.com"

  # 测试模式
  python3 woshipm_acquisition.py auto --product-url "https://example.com" --dry-run

  # 只搜文章
  python3 woshipm_acquisition.py search --keyword "产品经理"

  # 对指定文章评论
  python3 woshipm_acquisition.py comment --article-id 6397495
        """
    )
    subparsers = parser.add_subparsers(dest="command")

    # 搜索
    sp = subparsers.add_parser("search", help="搜索文章/问答")
    sp.add_argument("--keyword", "-k", required=True)
    sp.add_argument("--tab", type=int, default=0, help="0=文章 2=问答")
    sp.add_argument("--max-pages", type=int, default=5)

    # 评论
    cp = subparsers.add_parser("comment", help="评论指定文章")
    cp.add_argument("--article-id", required=True)
    cp.add_argument("--topic", default="")

    # 全自动
    ap = subparsers.add_parser("auto", help="全自动获客")
    ap.add_argument("--product-url", default="")
    ap.add_argument("--max-comments", type=int, default=5)
    ap.add_argument("--max-answers", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cookie", default="")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    env = load_env()
    cookie = args.cookie if hasattr(args, "cookie") and args.cookie else env.get("WOSHIPM_COOKIE", "")
    ac_config = load_acquisition_config()

    if args.command == "search":
        articles = search_all_pages(args.keyword, args.tab, max_pages=args.max_pages)
        total = len(articles)
        logger.info(f"共 {total} 条结果")
        for i, a in enumerate(articles[:10], 1):
            print(f"  [{i}] {a['title'][:50]}\n      {a['url']}  |  {a['author']}  |  {a['date']}")
        out = os.path.join(DATA_DIR, f"woshipm_search_{args.keyword}.json")
        with open(out, "w") as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ 已保存: {out}")

    elif args.command == "comment":
        article = {"article_id": args.article_id, "title": args.topic or "未知"}
        c = Commenter(cookie, ac_config)
        ok, msg = c.process(article)
        sys.exit(0 if ok else 1)

    elif args.command == "auto":
        if not args.dry_run and (not cookie or "your_" in cookie):
            logger.error("WOSHIPM_COOKIE 未配置，请检查 .env 文件（DRY-RUN 模式下可跳过）")
            sys.exit(1)
        auto = AutoAcquisition(cookie, ac_config, args.product_url)
        result = auto.run(args.max_comments, args.max_answers, args.dry_run)
        sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
