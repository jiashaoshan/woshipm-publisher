"""
Woshipm 热点获客发文 (v1.1.0)

流程: TrendRadar → 产品分析 → AI挑选 → LLM生成获客文章 → Pexels封面 → WordPress AJAX API 发布

使用:
  python3 scripts/woshipm-hotspot-publish.py --product-url "https://example.com"
  python3 scripts/woshipm-hotspot-publish.py --product-url "https://example.com" --dry-run
  python3 scripts/woshipm-hotspot-publish.py --product-url "https://example.com" --max 2
"""
import json, logging, os, sys, re, random, time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
DATA_DIR = SKILL_DIR / "data"
OUTPUT_DIR = SKILL_DIR / "output"
PUBLISH_RECORD = DATA_DIR / "hotspot-published.json"

sys.path.insert(0, str(SCRIPT_DIR))
from zhihu_llm import call_llm, call_llm_json, fetch_url_content

logger = logging.getLogger("woshipm-hotspot-publish")

WOSHIPM_COOKIE = os.environ.get("WOSHIPM_COOKIE", "")
DEFAULT_MCP_URL = os.environ.get("TRENDRADAR_URL", "http://100.111.235.91:3333/mcp")
MAX_TITLE_LEN = 30
MIN_BODY_LEN = 1500
MAX_BODY_LEN = 3000

# ====================================================================
# TrendRadar MCP 客户端（直连 HTTP）
# ====================================================================

def _mcp_init(url):
    import requests as _req
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
    }
    no_proxy = {"http": None, "https": None}
    r = _req.post(url, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "woshipm-hotspot-publish", "version": "1.0"},
        },
    }, headers=headers, proxies=no_proxy, timeout=10)
    sid = r.headers.get("mcp-session-id")
    if not sid:
        raise RuntimeError("MCP 初始化失败: 未返回 session-id")
    headers["Mcp-Session-Id"] = sid
    _req.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
              headers=headers, proxies=no_proxy, timeout=5)
    return sid, headers


def _mcp_call(method, args, url, headers):
    """调用 MCP 方法，处理 SSE 响应"""
    import requests as _req
    no_proxy = {"http": None, "https": None}
    r = _req.post(url, json={
        "jsonrpc": "2.0", "id": random.randint(1000, 9999),
        "method": method, "params": args,
    }, headers=headers, proxies=no_proxy, timeout=30)
    r.raise_for_status()
    # SSE 响应：逐行解析 data: 前缀的行
    body = r.text
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str:
                return json.loads(data_str)
    # 如果不是 SSE 格式，尝试直接解析 JSON
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        logger.error(f"MCP 响应非 JSON: {body[:300]}")
        raise ValueError("MCP 响应格式异常")


def mcp_call_tool(name, args, url):
    sid, headers = _mcp_init(url)
    return _mcp_call("tools/call", {"name": name, "arguments": args}, url, headers)


# ====================================================================
# 步骤1: 产品分析
# ====================================================================

def analyze_product_page(product_url):
    """分析产品页面，提取结构化信息"""
    logger.info(f"🔍 分析产品: {product_url}")
    page_content = fetch_url_content(product_url)

    if not page_content or len(page_content) < 100:
        logger.warning(f"  页面内容过少 ({len(page_content) if page_content else 0}字)，尝试 TrendRadar...")
        try:
            result = mcp_call_tool("read_article", {"url": product_url}, DEFAULT_MCP_URL)
            articles = (result.get("result", {}).get("content", []) or
                        result.get("content", []))
            for art in articles:
                text = (art.get("text", "") if isinstance(art, dict) else str(art))
                if len(text) > 200:
                    page_content = text[:5000]
                    logger.info(f"  TrendRadar 获取: {len(page_content)} 字")
                    break
        except Exception as e:
            logger.warning(f"  TrendRadar 读取失败: {e}")

    if not page_content or len(page_content.strip()) < 50:
        logger.error(f"  ❌ 无法获取产品页面内容")
        return None

    prompt_path = TEMPLATES_DIR / "product-analysis-prompt.md"
    if prompt_path.exists():
        template = prompt_path.read_text(encoding="utf-8")
    else:
        logger.error(f"  模板不存在: {prompt_path}")
        return None

    prompt = template.replace("{{product_url}}", product_url).replace("{{page_content}}", page_content)

    try:
        result = call_llm_json(
            system_prompt="你是一个产品分析专家，严格根据页面实际内容提取结构化信息，返回 JSON。",
            user_prompt=prompt,
        )
        logger.info(f"  ✅ 产品分析: {result.get('product_name', '未知')}")
        return result
    except Exception as e:
        logger.error(f"  ❌ 产品分析失败: {e}")
        return None


# ====================================================================
# 步骤2: 获取热点（新智元 RSS → V2EX 降级）
# ====================================================================

def fetch_rss_items():
    """从高质量 RSS 源获取 AI/科技热点（新智元、量子位、Hacker News）"""
    logger.info("📡 获取 AI/科技热点（RSS 优先）...")
    all_items = []

    # RSS 源：AI/科技类为主
    ai_feeds = ["xinzhiyuan", "liangziwei", "hacker-news"]
    try:
        result = mcp_call_tool("get_latest_rss", {"feeds": ai_feeds, "days": 1, "limit": 60, "include_summary": True}, DEFAULT_MCP_URL)
        content = result.get("result", {}).get("content", []) or result.get("content", [])
        for item in content:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            if not text:
                continue
            try:
                rss_data = json.loads(text) if isinstance(text, str) else text
                for article in (rss_data.get("data", []) if isinstance(rss_data, dict) else []):
                    title = article.get("title", "").strip()
                    url = article.get("url", "").strip()
                    summary = article.get("summary", article.get("content", ""))[:300]
                    feed_id = article.get("feed_id", article.get("feed_name", "科技"))
                    if not title:
                        continue
                    all_items.append({
                        "title": title,
                        "url": url,
                        "source": feed_id,
                        "content": summary or title,
                    })
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        logger.warning(f"  RSS 获取失败: {e}")

    if all_items:
        logger.info(f"  RSS 热点: {len(all_items)} 条")
        return all_items[:20]

    # 降级：从 PM 相关平台热榜获取
    logger.info("  RSS 无数据，降级平台热榜...")
    try:
        result = mcp_call_tool("get_latest_news", {"platforms": ["36kr", "zhihu", "v2ex", "juejin"], "limit": 20, "include_url": True}, DEFAULT_MCP_URL)
        content = result.get("result", {}).get("content", []) or result.get("content", [])
        seen_titles = set()
        for item in content:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            if not text:
                continue
            try:
                news_data = json.loads(text) if isinstance(text, str) else text
                for article in (news_data.get("data", []) if isinstance(news_data, dict) else []):
                    title = article.get("title", "").strip()
                    url = article.get("url", "").strip()
                    platform = article.get("platform", "热点").strip()
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)
                    all_items.append({
                        "title": title,
                        "url": url,
                        "source": platform,
                        "content": title,
                    })
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        logger.warning(f"  平台热榜获取失败: {e}")

    logger.info(f"  平台热点: {len(all_items)} 条")
    return all_items[:20]


def fetch_v2ex_topics():
    """最终降级方案"""
    logger.info("📡 最终降级...")
    try:
        result = mcp_call_tool("get_latest_news", {"platforms": ["v2ex", "36kr"], "limit": 15, "include_url": True}, DEFAULT_MCP_URL)
        content = result.get("result", {}).get("content", []) or result.get("content", [])
        items = []
        seen_titles = set()
        for item in content:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            if not text:
                continue
            try:
                news_data = json.loads(text) if isinstance(text, str) else text
                for article in (news_data.get("data", []) if isinstance(news_data, dict) else []):
                    title = article.get("title", "").strip()
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)
                    items.append({"title": title, "url": article.get("url",""), "source": article.get("platform","热点"), "content": title})
            except:
                pass
        logger.info(f"  降级热点: {len(items)} 条")
        return items[:15]
    except Exception as e:
        logger.warning(f"  降级失败: {e}")
        return []


# ====================================================================
# 步骤3: AI 挑选 + 生成获客文章
# ====================================================================

def select_and_rewrite(candidates, product_info, product_url, max_count=1):
    """AI 挑选最佳热点，逐个生成获客文章"""
    from copy import deepcopy

    if not candidates:
        logger.warning("  ⚠️ 无候选热点")
        return []

    # 构建挑选提示
    candidate_lines = []
    for i, c in enumerate(candidates):
        candidate_lines.append(f"[{i+1}] 标题: {c['title']}")
        candidate_lines.append(f"    来源: {c['source']}")
        ct = (c.get("content") or "")[:200].replace("\n", " ")
        if ct:
            candidate_lines.append(f"    摘要: {ct}")

    selection_prompt = (
        f"产品: {product_info.get('product_name', '未知')}\n"
        f"卖点: {product_info.get('tagline', '')}\n"
        f"目标用户: {product_info.get('target_audience', '')}\n"
        f"核心功能: {json.dumps(product_info.get('core_features', []), ensure_ascii=False)}\n"
        f"解决痛点: {json.dumps(product_info.get('pain_points_solved', []), ensure_ascii=False)}\n\n"
        f"候选热点:\n" + "\n".join(candidate_lines) + "\n\n"
        f"请选择最适合产品经理/行业分析角度的热点，返回JSON: {{\"index\": 序号, \"reason\": \"选择理由\"}}"
    )

    logger.info("🤖 AI 挑选最佳热点...")
    try:
        selection = call_llm_json(
            system_prompt="你是一个人人都是产品经理平台的选题策划，擅长挑选适合产品经理阅读的行业热点。",
            user_prompt=selection_prompt,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning(f"  AI 挑选失败: {e}，默认选第一个")
        selection = {"index": 1, "reason": "默认选择"}

    sel_idx = selection.get("index", 1)
    if isinstance(sel_idx, str):
        sel_idx = int(re.sub(r'\D', '', sel_idx) or 1)
    sel_idx = max(1, min(sel_idx, len(candidates))) - 1

    chosen = candidates[sel_idx]
    logger.info(f"  选中: [{sel_idx+1}] {chosen['title']}")
    logger.info(f"  理由: {selection.get('reason', '')}")

    # 获取热点全文
    logger.info("📖 获取热点文章全文...")
    full_content = chosen.get("content", "")
    if chosen.get("url") and len(full_content) < 300:
        try:
            result = mcp_call_tool("read_article", {"url": chosen["url"]}, DEFAULT_MCP_URL)
            articles = (result.get("result", {}).get("content", []) or
                        result.get("content", []))
            for art in articles:
                text = (art.get("text", "") if isinstance(art, dict) else str(art))
                if len(text) > len(full_content):
                    full_content = text[:3000]
                    break
        except Exception as e:
            logger.warning(f"  获取全文失败: {e}")

    logger.info(f"  ✅ 获取内容 ({len(full_content)}字)")

    # 读取文章生成模板
    prompt_path = TEMPLATES_DIR / "hotspot-acquisition-prompt.md"
    if not prompt_path.exists():
        logger.error(f"  模板不存在: {prompt_path}")
        return []

    template = prompt_path.read_text(encoding="utf-8")

    articles = []
    article_prompt = (
        template
        .replace("{{hotspot_title}}", chosen["title"])
        .replace("{{hotspot_url}}", chosen.get("url", ""))
        .replace("{{hotspot_source}}", chosen.get("source", ""))
        .replace("{{hotspot_content}}", full_content)
        .replace("{{product_name}}", product_info.get("product_name", ""))
        .replace("{{product_url}}", product_url)
        .replace("{{tagline}}", product_info.get("tagline", ""))
        .replace("{{core_features}}", json.dumps(product_info.get("core_features", []), ensure_ascii=False))
        .replace("{{pain_points_solved}}", json.dumps(product_info.get("pain_points_solved", []), ensure_ascii=False))
        .replace("{{user_value}}", product_info.get("user_value", ""))
        .replace("{{tech_stack}}", product_info.get("tech_stack", ""))
    )

    logger.info(f"✍️ 生成文章: {chosen['title'][:30]}...")
    try:

        raw = call_llm(
            system_prompt="你是一位人人都是产品经理社区的资深作者，擅长从产品经理视角分析行业动态和趋势。输出必须包含 ===TITLE===、===BRIEF===、===BODY===、===END=== 标记。正文为纯文本，不要 Markdown 语法。",
            user_prompt=article_prompt,
            temperature=0.7,
            max_tokens=4096,
        )

        parsed = parse_article_output(raw)
        if not parsed:
            logger.warning(f"  解析失败，原始输出: {raw[:100]}...")
            return []

        parsed["hotspot_title"] = chosen["title"]
        parsed["hotspot_url"] = chosen.get("url", "")
        title_preview = parsed["title"][:30]
        body_len = len(parsed.get("body", ""))
        logger.info(f"  ✅ 标题: {title_preview} | 正文: {body_len}字")
        articles.append(parsed)

    except Exception as e:
        logger.error(f"  ❌ 生成失败: {e}")

    return articles


def parse_article_output(raw):
    """解析 LLM 输出的 ===TITLE=== / ===BRIEF=== / ===BODY=== / ===END=== 格式"""
    title = ""
    brief = ""
    body = ""

    title_m = re.search(r'===TITLE===\s*(.+?)(?:\s*===)', raw, re.DOTALL)
    if title_m:
        title = title_m.group(1).strip()

    brief_m = re.search(r'===BRIEF===\s*(.+?)(?:\s*===)', raw, re.DOTALL)
    if brief_m:
        brief = brief_m.group(1).strip()

    body_m = re.search(r'===BODY===\s*(.+?)(?:\s*===)', raw, re.DOTALL)
    if body_m:
        body = body_m.group(1).strip()

    if not title or not body:
        # 容错解析
        lines = raw.strip().split("\n")
        mode = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("===TITLE==="):
                mode = "title"
                continue
            elif stripped.startswith("===BRIEF==="):
                mode = "brief"
                continue
            elif stripped.startswith("===BODY==="):
                mode = "body"
                continue
            elif stripped.startswith("===END==="):
                mode = None
                continue

            if mode == "title":
                title = (title + " " + stripped).strip()
            elif mode == "brief":
                brief = (brief + " " + stripped).strip()
            elif mode == "body":
                body = (body + "\n" + stripped).strip()

    return {"title": title, "brief": brief, "body": body} if title and body else None


# ====================================================================
# Pexels 封面图
# ====================================================================

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "ogysj3gEKHiYFCgRdzo7PiDGyvgxRwxPldwkiANpAOvepyHrNa9q71lR")
COVERS_DIR = SKILL_DIR / "data" / "covers"

def ensure_covers_dir():
    COVERS_DIR.mkdir(parents=True, exist_ok=True)


def search_pexels(keyword):
    import requests as _req
    try:
        q = keyword.replace(" ", "+")
        url = f"https://api.pexels.com/v1/search?query={q}&per_page=5&orientation=landscape&size=large"
        resp = _req.get(url, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        photos = data.get("photos", [])
        if photos:
            photo = random.choice(photos)
            src = photo.get("src", {})
            return src.get("large2x") or src.get("large") or src.get("original", "")
    except Exception as e:
        logger.warning(f"  Pexels 搜索失败: {e}")
    return ""


def download_image(url, save_path):
    """下载图片到本地文件"""
    import requests as _req
    try:
        resp = _req.get(url, timeout=30)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(resp.content)
        logger.info(f"  ✅ 已下载: {save_path.name} ({len(resp.content)} bytes)")
        return str(save_path)
    except Exception as e:
        logger.warning(f"  下载失败: {e}")
    return ""


def extract_cover_keyword(title, product_info):
    combined = (title + " " + product_info.get("tagline", "")
                + " " + product_info.get("product_name", ""))
    words = re.sub(r'[^\w一-鿿]', ' ', combined).split()
    meaningful = [w for w in words if len(w) > 1]
    if meaningful:
        import random as _r
        return _r.choice(meaningful[:5])
    return "technology"


def generate_cover(article, product_info):
    """生成封面图：搜索 Pexels → 下载到本地"""
    keyword = extract_cover_keyword(article["title"], product_info)
    logger.info(f"  🖼️ 封面关键词: {keyword}")
    url = search_pexels(keyword)
    if url:
        logger.info(f"  ✅ 封面 URL: {url[:60]}...")
        ensure_covers_dir()
        safe = re.sub(r'[^a-zA-Z0-9_-]', '', article["title"])[:30] or "cover"
        local_path = COVERS_DIR / f"{safe}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        local_file = download_image(url, local_path)
        if local_file:
            return local_file
    logger.info("  ⏭️ 未获取到封面")
    return ""


# ====================================================================
# WordPress AJAX API 发布
# ====================================================================

def publish_via_api(title, body, copyright_agreed=True):
    """通过 WordPress AJAX API 提交文章审核（action=add_pending）"""
    cookie = WOSHIPM_COOKIE
    if not cookie:
        logger.error("  ❌ 未配置 WOSHIPM_COOKIE，无法发布")
        return False

    logger.info(f"  📤 提交审核: {title[:30]}... ({len(body)}字)")

    data = {
        "action": "add_pending",
        "post_title": title[:MAX_TITLE_LEN] if len(title) > MAX_TITLE_LEN else title,
        "post_content": body,
    }
    if copyright_agreed:
        data["copyright"] = "1"
        data["copyright_other"] = "1"
        data["copyright_pm"] = "1"

    try:
        import requests
        resp = requests.post(
            "https://www.woshipm.com/wp-admin/admin-ajax.php",
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": cookie,
            },
            timeout=30,
        )
        try:
            result = resp.json()
        except Exception:
            logger.error(f"  响应非 JSON: {resp.text[:200]}")
            return False

        success = result.get("success")
        if success == 1 or success is True:
            logger.info(f"  ✅ 文章已提交审核: {title[:30]}")
            return True
        else:
            msg = result.get("message", result.get("msg", "未知错误"))
            logger.error(f"  ❌ 提交失败: {msg}")
            return False

    except Exception as e:
        logger.error(f"  ❌ 发布请求异常: {e}")
        return False


def save_draft_via_api(title, body):
    """通过 WordPress AJAX API 保存草稿（action=add_draft）"""
    cookie = WOSHIPM_COOKIE
    if not cookie:
        logger.error("  ❌ 未配置 WOSHIPM_COOKIE，无法保存草稿")
        return False

    logger.info(f"  📄 保存草稿: {title[:30]}...")

    data = {
        "action": "add_draft",
        "post_title": title[:MAX_TITLE_LEN] if len(title) > MAX_TITLE_LEN else title,
        "post_content": body,
    }

    try:
        import requests
        resp = requests.post(
            "https://www.woshipm.com/wp-admin/admin-ajax.php",
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": cookie,
            },
            timeout=30,
        )
        try:
            result = resp.json()
        except Exception:
            logger.error(f"  响应非 JSON: {resp.text[:200]}")
            return False

        post_id = result.get("post_id")
        url = result.get("url", "")
        if post_id:
            logger.info(f"  ✅ 草稿已保存 (ID: {post_id})")
            if url:
                logger.info(f"  🔗 预览: {url}")
            return True
        else:
            logger.error(f"  ❌ 保存草稿失败: {str(result)[:200]}")
            return False

    except Exception as e:
        logger.error(f"  ❌ 保存草稿异常: {e}")
        return False


# ====================================================================
# 持久化
# ====================================================================

def save_markdown(article, index):
    """保存文章到 output/ 目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[^一-鿿\w-]', '', article["title"])[:20]
    fname = f"hotspot-{datetime.now().strftime('%Y%m%d')}-{index}.md"
    fpath = OUTPUT_DIR / fname
    md = "\n".join([
        "---",
        f'title: "{article["title"]}"',
        f'description: "{article.get("brief", "")}"',
        f'hotspot: "{article.get("hotspot_title", "")}"',
        f'cover: "{article.get("cover_path", "")}"',
        "---",
        "",
        article["body"],
    ])
    fpath.write_text(md, encoding="utf-8")
    logger.info(f"  💾 已保存: {fname}")
    return str(fpath)


def save_published(record):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    if PUBLISH_RECORD.exists():
        try:
            records = json.loads(PUBLISH_RECORD.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(record)
    PUBLISH_RECORD.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ====================================================================
# 主流程
# ====================================================================

def run(product_url, dry_run=False, max_count=1, auto_confirm=False):
    """主入口"""
    logger.info("=" * 50)
    logger.info("📝 Woshipm 热点获客发文 v1.0.0")
    logger.info("=" * 50)
    logger.info(f"  产品: {product_url}")
    logger.info(f"  模式: {'Dry-run' if dry_run else 'LIVE'}")
    logger.info(f"  最多: {max_count} 篇")

    # ═══ 步骤1: 产品分析 ═══
    logger.info("\n" + "═" * 50)
    logger.info("步骤1: 分析产品...")
    product_info = analyze_product_page(product_url)
    if not product_info:
        logger.error("  ❌ 产品分析失败")
        return {"status": "failed", "error": "产品分析失败"}

    # ═══ 步骤2: 获取热点 ═══
    logger.info("\n" + "═" * 50)
    logger.info("步骤2: 获取热点...")
    candidates = fetch_rss_items()
    if not candidates:
        logger.warning("  RSS 无数据，降级 V2EX...")
        candidates = fetch_v2ex_topics()
    if not candidates:
        logger.error("  ❌ 所有渠道均无热点")
        return {"status": "failed", "error": "无热点数据"}
    logger.info(f"  候选热点: {len(candidates)} 条")

    # ═══ 步骤3: 挑选 + 生成获客文章 ═══
    logger.info("\n" + "═" * 50)
    logger.info("步骤3: AI 挑选热点 + 生成获客文章...")
    articles = select_and_rewrite(candidates, product_info, product_url, max_count)
    if not articles:
        logger.error("  ❌ 文章生成失败")
        return {"status": "failed", "error": "文章生成失败"}
    logger.info(f"  生成 {len(articles)} 篇文章")

    # ═══ 步骤4: Pexels 封面 + 保存 ═══
    logger.info("\n" + "═" * 50)
    logger.info("步骤4: 生成封面 + 保存...")
    results = []
    for i, article in enumerate(articles):
        logger.info(f"\n  [{i+1}/{len(articles)}] {article['title'][:30]}...")

        body_chars = len(article["body"].strip())
        if body_chars < MIN_BODY_LEN:
            logger.warning(f"    正文 {body_chars}字 < 建议 {MIN_BODY_LEN}字")
        if body_chars > MAX_BODY_LEN:
            logger.warning(f"    正文 {body_chars}字 > 建议 {MAX_BODY_LEN}字")

        cover_path = generate_cover(article, product_info)
        article["cover_path"] = cover_path

        save_markdown(article, i + 1)

        if dry_run:
            logger.info("    ⏭️ Dry-run，跳过发布")
            results.append({
                "index": i + 1,
                "title": article["title"],
                "char_count": body_chars,
                "status": "skipped",
            })
            continue

        # 发布（通过 WordPress AJAX API 提交审核）
        pub_ok = publish_via_api(
            title=article["title"],
            body=article["body"],
        )

        if pub_ok:
            record = {
                "title": article["title"],
                "hotspot_title": article["hotspot_title"],
                "hotspot_url": article["hotspot_url"],
                "product_url": product_url,
                "char_count": body_chars,
                "published_at": datetime.now().isoformat(),
                "type": "热点获客",
            }
            save_published(record)
            logger.info(f"    ✅ 发布成功")
            results.append({
                "index": i + 1,
                "title": article["title"],
                "char_count": body_chars,
                "status": "published",
            })
        else:
            logger.error(f"    ❌ 发布失败")
            results.append({
                "index": i + 1,
                "title": article["title"],
                "char_count": body_chars,
                "status": "failed",
            })

    logger.info("\n" + "=" * 50)
    logger.info("📊 汇总")
    logger.info("=" * 50)
    for r in results:
        status_icon = "✅" if r["status"] == "published" else "⏭️" if r["status"] == "skipped" else "❌"
        logger.info(f"  {status_icon} [{r['index']}] {r['title'][:30]} ({r['char_count']}字)")
    logger.info(f"\n  共 {len(results)}/{len(articles)} 篇成功")

    return {"status": "ok", "results": results}


# ====================================================================
# CLI 入口
# ====================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Woshipm 热点获客发文")
    parser.add_argument("--product-url", required=True, help="产品链接")
    parser.add_argument("--dry-run", action="store_true", help="仅测试，不发布")
    parser.add_argument("--max", type=int, default=1, help="最多生成文章数（默认 1）")
    parser.add_argument("--auto", action="store_true", help="自动确认（跳过手动确认）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    result = run(
        product_url=args.product_url,
        dry_run=args.dry_run,
        max_count=args.max,
        auto_confirm=args.auto,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
