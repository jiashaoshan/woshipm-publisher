#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人人都是产品经理(woshipm) 搜索爬虫
基于 AJAX 接口: POST https://api.woshipm.com/search/result.html
提取所有搜索结果的 文章URL + 文章标题
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
import logging
from datetime import datetime
from pathlib import Path

# ─── 路径配置 ─────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SKILL_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ─── 日志 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── 常量 ─────────────────────────────────────────────────
SEARCH_URL = "https://api.woshipm.com/search/result.html"
ARTICLE_URL_TEMPLATE = "https://www.woshipm.com/active/{article_id}.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://api.woshipm.com/search/list.html",
    "Origin": "https://api.woshipm.com",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def search_page(keyword: str, page: int = 1, tab: int = 0,
                sort_type: int = 0) -> tuple[list[dict], int]:
    """
    请求单页搜索结果

    Args:
        keyword: 搜索关键词
        page: 页码
        tab: 搜索类型 0=文章
        sort_type: 排序 0=综合

    Returns:
        (articles, total_count)
        articles: [{"article_id": "xxx", "title": "xxx", "url": "xxx", "author": "xxx", "date": "xxx", "views": "xxx"}, ...]
        total_count: 总文章数
    """
    data = f"key={urllib.parse.quote(keyword)}&tab={tab}&page={page}&idSearch=&sortType={sort_type}"
    req = urllib.request.Request(SEARCH_URL, data=data.encode("utf-8"), headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        logger.error(f"HTTP {e.code}: {e.reason}")
        return [], 0
    except Exception as e:
        logger.error(f"请求失败: {e}")
        return [], 0

    articles = []
    total_count = 0

    # ── 提取总数 ──
    count_match = re.search(r"(\d+)", html)
    if count_match:
        total_count = int(count_match.group(1))

    # ── 提取文章 ──
    # 每个文章块: <div class="course--item" ... id=文章ID>
    #   内部: <a ... class="title">标题</a>
    #   内部: <span class="pull-left">作者 · 日期</span>
    #   内部: <span class="pull-right"> 阅读 xxx </span>

    items = re.split(r'<div class="course--item"', html)[1:]  # 跳过第一个分割前的空白

    for item in items:
        # 文章ID
        id_match = re.search(r'id\s*=\s*(\d+)', item)
        if not id_match:
            continue
        article_id = id_match.group(1)

        # 标题（去除搜索高亮的 span 标签）
        title_match = re.search(r'class="title"[^>]*>(.*?)</a>', item, re.DOTALL)
        if not title_match:
            continue
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        if not title:
            continue

        # 作者 + 日期
        author_match = re.search(r'class="pull-left">(.*?)</span>', item)
        author_info = html_mod.unescape(author_match.group(1).strip()) if author_match else ""
        author = ""
        date_str = ""
        if "·" in author_info:
            parts = author_info.split("·", 1)
            author = parts[0].strip()
            date_str = parts[1].strip() if len(parts) > 1 else ""

        # 阅读量
        views_match = re.search(r'阅读\s*([\d.kw万]+)', html_mod.unescape(item))
        views = views_match.group(1) if views_match else ""

        url = ARTICLE_URL_TEMPLATE.format(article_id=article_id)

        articles.append({
            "article_id": article_id,
            "title": title,
            "url": url,
            "author": author,
            "date": date_str,
            "views": views,
        })

    return articles, total_count


def search_all(keyword: str, tab: int = 0, sort_type: int = 0,
               max_pages: int = 0, delay: float = 1.0) -> list[dict]:
    """
    遍历所有分页，获取全部搜索结果

    Args:
        keyword: 搜索关键词
        tab: 搜索类型
        sort_type: 排序方式
        max_pages: 最大页数(0=不限制)
        delay: 页间延迟(秒)

    Returns:
        所有文章的列表
    """
    all_articles = []
    page = 1

    while True:
        logger.info(f"  请求第 {page} 页...")
        articles, total_count = search_page(keyword, page, tab, sort_type)

        if page == 1:
            logger.info(f"  共 {total_count} 篇文章，每页约 {len(articles)} 篇")

        if not articles:
            logger.info(f"  第 {page} 页无结果，搜索结束")
            break

        all_articles.extend(articles)
        logger.info(f"  ✓ 第 {page} 页: 提取 {len(articles)} 篇 (累计 {len(all_articles)})")

        # 检查是否到最后一页
        if max_pages > 0 and page >= max_pages:
            logger.info(f"  达到最大页数限制 {max_pages}")
            break

        # 本页文章数少于预期 = 最后一页
        if len(articles) < 10:
            logger.info(f"  已到最后一页")
            break

        page += 1
        if delay > 0:
            time.sleep(delay)

    return all_articles


def main():
    parser = argparse.ArgumentParser(
        description="人人都是产品经理(woshipm) 搜索爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 搜索并保存全部结果
  python3 woshipm_search.py --keyword "token"

  # 只搜前3页
  python3 woshipm_search.py --keyword "AI产品经理" --max-pages 3

  # 输出到指定文件
  python3 woshipm_search.py --keyword "需求分析" --output results.json
        """
    )
    parser.add_argument("--keyword", "-k", required=True, help="搜索关键词")
    parser.add_argument("--tab", type=int, default=0, help="搜索类型 (0=文章)")
    parser.add_argument("--sort-type", type=int, default=0, help="排序 (0=综合)")
    parser.add_argument("--max-pages", type=int, default=0, help="最大页数 (0=全部)")
    parser.add_argument("--delay", type=float, default=1.5, help="页间延迟秒数")
    parser.add_argument("--output", "-o", default="", help="输出文件路径")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"woshipm 搜索: \"{args.keyword}\"")
    logger.info("=" * 60)

    articles = search_all(
        keyword=args.keyword,
        tab=args.tab,
        sort_type=args.sort_type,
        max_pages=args.max_pages,
        delay=args.delay,
    )

    logger.info("\n" + "=" * 60)
    logger.info(f"完成! 共提取 {len(articles)} 篇文章")
    logger.info("=" * 60)

    # 打印摘要
    for i, a in enumerate(articles[:10], 1):
        print(f"  [{i}] {a['title'][:50]}")
        print(f"      {a['url']}  |  {a['author']}  |  {a['date']}  |  阅读 {a['views']}")
    if len(articles) > 10:
        print(f"  ... 还有 {len(articles) - 10} 篇")

    # 保存
    output_file = args.output
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_keyword = re.sub(r'[\\/:*?"<>|]', '_', args.keyword)
        output_file = os.path.join(DATA_DIR, f"woshipm_{safe_keyword}_{timestamp}.json")

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    logger.info(f"✓ 已保存: {output_file}")


if __name__ == "__main__":
    main()
