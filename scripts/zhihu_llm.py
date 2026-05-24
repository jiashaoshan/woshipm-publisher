#!/usr/bin/env python3
"""
LLM 调用模块 — 封装百度千帆 API 调用
支持从环境变量/配置文件读取 API Key
"""
import functools
import json
import logging
import os
import re
import requests
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── LLM 配置 ────
LLM_API_URL = None
LLM_API_KEY = None
DEFAULT_MODEL = "qianfan-code-latest"
DEFAULT_TIMEOUT = 120

# 配置文件路径
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(SKILL_DIR, "config", "llm.json")

PROVIDER_URLS = {
    "baiduqianfancodingplan": "https://qianfan.baidubce.com/v2/coding",
    "deepseek": "https://api.deepseek.com",
    "sensenova": "https://token.sensenova.cn/v1",
}

PROVIDER_MODELS = {
    "baiduqianfancodingplan": "qianfan-code-latest",
    "deepseek": "deepseek-v4-flash",
    "sensenova": "deepseek-v4-flash",
}


def _load_llm_config():
    """从 config/llm.json 读取 LLM 配置"""
    global LLM_API_URL, LLM_API_KEY, DEFAULT_MODEL
    if LLM_API_URL and LLM_API_KEY:
        return

    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(
            f"LLM 配置文件不存在: {CONFIG_FILE}\n"
            f"请在 config/llm.json 中配置 provider、api_key、model"
        )

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        provider = cfg.get("provider", "baiduqianfancodingplan")
        api_key = cfg.get("api_key", "")
        model = cfg.get("model", "")

        base_url = PROVIDER_URLS.get(provider)
        if not base_url:
            raise ValueError(f"不支持的 provider: {provider}，支持: {list(PROVIDER_URLS.keys())}")
        if not api_key:
            raise ValueError(f"config/llm.json 中未配置 api_key")

        LLM_API_URL = base_url + "/chat/completions"
        LLM_API_KEY = api_key
        DEFAULT_MODEL = model or PROVIDER_MODELS.get(provider, "qianfan-code-latest")
        logger.info(f"LLM 配置: {LLM_API_URL} | 模型: {DEFAULT_MODEL}")
    except Exception as e:
        logger.error(f"读取 {CONFIG_FILE} 失败: {e}")
        raise


def get_llm_api_url() -> str:
    _load_llm_config()
    return LLM_API_URL


def get_api_key() -> str:
    _load_llm_config()
    if not LLM_API_KEY:
        raise EnvironmentError(
            "未找到 LLM API Key。\n"
            f"请在 {CONFIG_FILE} 中配置 api_key"
        )
    return LLM_API_KEY


@functools.lru_cache(maxsize=16)
def fetch_url_content(url: str, max_chars: int = 5000) -> str:
    """
    抓取 URL 页面内容，提取可读文本摘要

    Args:
        url: 目标 URL
        max_chars: 最大返回字符数

    Returns:
        str: 结构化的页面内容摘要，失败时返回空字符串
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    logger.info(f"⎿ 抓取页面: {url[:60]}...")

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        # 检测编码
        content_type = resp.headers.get("content-type", "")
        if "charset" in content_type.lower():
            resp.encoding = resp.apparent_encoding
        else:
            resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        # 移除无用标签
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        parts = []

        # 标题
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            parts.append(f"【页面标题】{title_tag.get_text(strip=True)}")

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content", "").strip():
            parts.append(f"【页面描述】{meta_desc['content'].strip()}")

        # 一级标题
        for h in soup.find_all(["h1", "h2", "h3"], limit=15):
            text = h.get_text(strip=True)
            if text and len(text) > 1:
                parts.append(f"【{h.name.upper()}】{text}")

        # 段落文本
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 15:  # 过滤太短的无意义段落
                parts.append(text)

        # 列表项
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if 10 < len(text) < 200:
                parts.append(f"• {text}")

        content = "\n\n".join(parts)
        # 合并多余空白
        content = re.sub(r'\n{3,}', '\n\n', content).strip()

        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n...（内容过长，截断至 {max_chars} 字符）"

        logger.info(f"✓ 页面抓取完成: {len(content)} 字符")
        return content

    except requests.Timeout:
        logger.warning(f"页面抓取超时: {url[:60]}")
        return ""
    except requests.RequestException as e:
        logger.warning(f"页面抓取失败: {url[:60]} - {e}")
        return ""
    except Exception as e:
        logger.warning(f"页面解析失败: {e}")
        return ""


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    调用 LLM API（OpenAI 兼容接口）

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        model: 模型名称，默认 qianfan-code-latest
        temperature: 温度参数
        max_tokens: 最大生成 token 数
        response_format: 响应格式，如 {"type": "json_object"}
        timeout: 超时时间（秒）

    Returns:
        str: LLM 返回的文本内容

    Raises:
        requests.RequestException: API 调用失败
        ValueError: API 返回异常
    """
    api_key = get_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if response_format:
        payload["response_format"] = response_format

    logger.debug(f"LLM 请求: model={model}, system_prompt_len={len(system_prompt)}, user_prompt_len={len(user_prompt)}")

    try:
        resp = requests.post(
            get_llm_api_url(),
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        logger.debug(f"LLM 响应: {len(content)} 字符")
        return content

    except requests.exceptions.Timeout:
        logger.error(f"LLM 请求超时 (>{timeout}s)")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM 请求失败: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                err_detail = e.response.json()
                logger.error(f"API 错误详情: {json.dumps(err_detail, ensure_ascii=False)}")
            except Exception:
                logger.error(f"API 原始响应: {e.response.text[:500]}")
        raise
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.error(f"解析 LLM 响应失败: {e}")
        raise ValueError(f"LLM 返回格式异常: {e}")


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    调用 LLM 并解析 JSON 响应
    注意：不使用 response_format 约束（避免截断输出），提示词已要求JSON格式

    Returns:
        dict: 解析后的 JSON 对象
    """
    content = call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    # 尝试解析 JSON
    # 先剥离 markdown 代码块标记
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped.rsplit("```", 1)[0]
    stripped = stripped.strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON 对象或数组
        import re
        for pattern in [r'\{.*\}', r'\[.*\]']:
            json_match = re.search(pattern, stripped, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    continue
        logger.warning(f"LLM 返回非 JSON 格式，原始内容: {stripped[:200]}...")
        raise ValueError(f"LLM 返回不是有效的 JSON: {stripped[:100]}...")


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.DEBUG)
    try:
        key = get_api_key()
        print(f"✓ API Key 找到: {key[:8]}...{key[-4:]}")
    except EnvironmentError as e:
        print(f"✗ {e}")
        exit(1)
