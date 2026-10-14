"""公网检索：默认 DuckDuckGo（无需 API Key），可选 Tavily / Bing / SerpAPI。

结果只保留标题、URL 与摘要。失败或离线时明确说明，不编造来源。
"""
from __future__ import annotations

import asyncio
import base64
import html
import ipaddress
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from sqlalchemy.orm import Session

SEARCH_TIMEOUT_SECONDS = 15.0
# 单个端点的上限。默认检索会并行尝试多个无密钥端点，避免某一个挂满 15 秒就整次失败。
ENDPOINT_TIMEOUT_SECONDS = 8.0
_DDG_GRACE_SECONDS = 1.5
MAX_RESULTS = 5
MAX_FETCH_BYTES = 200_000
MAX_QUERY_CHARS = 180
MAX_SNIPPET_CHARS = 320

_PROVIDERS = ("duckduckgo", "tavily", "bing", "serpapi")
_PAID_PROVIDERS = ("tavily", "bing", "serpapi")

# 这些说法走 web_search，不走企业 FAQ 短路。
_WEB_PHRASE_RE = re.compile(
    r"联网|网上查|网上看看|网上搜索|搜索一下|查一下最新|公开资料|查资料|上网查|中标公告"
)
_FETCH_HINT_RE = re.compile(r"打开|访问|抓取|读取链接|这个链接|这个网址|打开链接|看看这个")
_URL_RE = re.compile(r"https?://[^\s<>\"'）】\]]+", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_DDG_ANCHOR_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'|<a[^>]*href="([^"]+)"[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIPPET_RE = re.compile(
    r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|span)>',
    re.IGNORECASE | re.DOTALL,
)
_LITE_RE = re.compile(
    r'<a[^>]*class=[\'"]result-link[\'"][^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'|<a[^>]*href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LEAD_RE = re.compile(
    r"^(?:请|帮我|帮忙|麻烦|你)?"
    r"(?:联网查一下|联网搜索一下|联网搜一下|联网查一查|联网搜索|联网查|联网看看|联网|"
    r"网上查一下|网上搜索一下|网上查一查|网上搜索|网上查|网上看看|"
    r"上网查一下|上网搜索|上网查|"
    r"搜索一下|搜一下|"
    r"查一下最新的|查一下最新|查一下|查一查|查资料|"
    r"帮我查一下|帮我查)*"
)


def text_requests_web_search(text: str) -> bool:
    return bool(_WEB_PHRASE_RE.search(text or ""))


def should_search(text: str, context: dict | None = None) -> bool:
    if (context or {}).get("web_search") is True:
        return True
    return text_requests_web_search(text)


def explicit_fetch_url(text: str) -> str:
    """仅当用户明确要求打开某个 http(s) 链接时返回该 URL。"""
    raw = text or ""
    if not _FETCH_HINT_RE.search(raw):
        return ""
    match = _URL_RE.search(raw)
    if not match:
        return ""
    url = match.group(0).rstrip(".,;，。)")
    return url if _is_allowed_http_url(url) else ""


def extract_search_query(text: str) -> str:
    q = (text or "").strip()
    q = _URL_RE.sub(" ", q)
    q = _LEAD_RE.sub("", q).strip(" ：:，,。！？?!\"'「」")
    q = re.sub(r"\s+", " ", q).strip()
    if len(q) < 2:
        q = re.sub(r"\s+", " ", (text or "")).strip()
        q = _URL_RE.sub(" ", q).strip()
    return q[:MAX_QUERY_CHARS]


def strip_html(raw: str) -> str:
    text = _SCRIPT_RE.sub(" ", raw or "")
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clip(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _is_allowed_http_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    if any((
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_reserved,
        ip.is_multicast,
        ip.is_unspecified,
    )):
        return False
    return True


def _unwrap_ddg_href(href: str) -> str:
    href = html.unescape((href or "").strip())
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    uddg = parse_qs(parsed.query).get("uddg")
    if uddg:
        href = unquote(uddg[0])
    return href.strip()


def _push_result(items: list[dict[str, str]], seen: set[str], title: str, url: str, snippet: str) -> None:
    url = _unwrap_ddg_href(url)
    if not _is_allowed_http_url(url) or url in seen:
        return
    title = _clip(strip_html(title), 160) or url
    snippet = _clip(strip_html(snippet))
    seen.add(url)
    items.append({"title": title, "url": url, "snippet": snippet})


def parse_duckduckgo_html(raw: str) -> list[dict[str, str]]:
    """从 DuckDuckGo HTML / Lite 页面抽出最多 5 条结果。"""
    page = raw or ""
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    anchors = list(_DDG_ANCHOR_RE.finditer(page))
    if anchors:
        for index, match in enumerate(anchors):
            href = match.group(1) or match.group(3) or ""
            title = match.group(2) or match.group(4) or ""
            end = anchors[index + 1].start() if index + 1 < len(anchors) else match.end() + 1200
            window = page[match.end():end]
            snippet_match = _DDG_SNIPPET_RE.search(window)
            snippet = snippet_match.group(1) if snippet_match else ""
            _push_result(items, seen, title, href, snippet)
            if len(items) >= MAX_RESULTS:
                return items
        return items

    lite = list(_LITE_RE.finditer(page))
    for index, match in enumerate(lite):
        href = match.group(1) or match.group(3) or ""
        title = match.group(2) or match.group(4) or ""
        end = lite[index + 1].start() if index + 1 < len(lite) else match.end() + 800
        window = page[match.end():end]
        snippet_match = re.search(
            r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</',
            window,
            re.IGNORECASE | re.DOTALL,
        )
        snippet = snippet_match.group(1) if snippet_match else ""
        _push_result(items, seen, title, href, snippet)
        if len(items) >= MAX_RESULTS:
            break
    return items


def parse_duckduckgo_instant(payload: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    abstract_url = str(payload.get("AbstractURL") or "")
    abstract = str(payload.get("AbstractText") or "")
    heading = str(payload.get("Heading") or "")
    if abstract and abstract_url:
        _push_result(items, seen, heading or abstract[:40], abstract_url, abstract)

    def walk(nodes: list[Any]) -> None:
        for node in nodes or []:
            if not isinstance(node, dict) or len(items) >= MAX_RESULTS:
                continue
            if node.get("Topics"):
                walk(node.get("Topics") or [])
                continue
            text = str(node.get("Text") or "")
            url = str(node.get("FirstURL") or "")
            title = text.split(" - ", 1)[0] if text else url
            _push_result(items, seen, title, url, text)

    walk(payload.get("RelatedTopics") or [])
    return items[:MAX_RESULTS]


_BING_H2_RE = re.compile(
    r"<h2[^>]*>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*</h2>",
    re.IGNORECASE | re.DOTALL,
)


def _unwrap_bing_href(href: str) -> str:
    """Bing 结果链接经常包在 /ck/a 跳转里，u=a1 后面是目标网址的 base64。"""
    href = html.unescape((href or "").strip())
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower()
    if not host.endswith("bing.com") or not parsed.path.startswith("/ck/"):
        return href
    raw = (parse_qs(parsed.query).get("u") or [""])[0]
    if not raw.startswith("a1"):
        return ""
    blob = raw[2:]
    blob += "=" * ((4 - len(blob) % 4) % 4)
    try:
        decoded = base64.b64decode(blob).decode("utf-8", "replace")
    except Exception:
        return ""
    return decoded if decoded.startswith("http") else ""


def parse_bing_html(raw: str) -> list[dict[str, str]]:
    """从 Bing 搜索页抽出最多 5 条公开结果。跳转跟踪链接还原成目标 URL。"""
    page = raw or ""
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    matches = list(_BING_H2_RE.finditer(page))
    for index, match in enumerate(matches):
        href = _unwrap_bing_href(match.group(1))
        title = match.group(2)
        end = matches[index + 1].start() if index + 1 < len(matches) else match.end() + 800
        window = page[match.end():end]
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", window, re.IGNORECASE | re.DOTALL)
        snippet = snippet_match.group(1) if snippet_match else ""
        _push_result(items, seen, title, href, snippet)
        if len(items) >= MAX_RESULTS:
            break
    return items


def _httpx_client(timeout: float = SEARCH_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    verify: bool | str = True
    try:
        import certifi

        verify = certifi.where()
    except Exception:
        verify = True
    budget = float(timeout or SEARCH_TIMEOUT_SECONDS)
    # 连接阶段单独收紧，避免坏掉的 IPv6 路由把整次检索拖到读超时。
    request_timeout = httpx.Timeout(budget, connect=min(5.0, budget))
    transport = None
    try:
        transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=0)
    except Exception:
        transport = None
    kwargs: dict[str, Any] = {}
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.AsyncClient(
        timeout=request_timeout,
        follow_redirects=True,
        verify=verify,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        **kwargs,
    )


def _failure(
    *,
    provider: str,
    query: str,
    message: str,
    error: str,
    offline: bool = False,
    empty_state: bool = False,
) -> dict[str, Any]:
    return {
        "ok": False,
        "provider": provider,
        "query": query,
        "results": [],
        "offline": offline,
        "empty_state": empty_state,
        "error": error,
        "message": message,
    }


def _success(provider: str, query: str, results: list[dict[str, str]], message: str = "") -> dict[str, Any]:
    clipped = results[:MAX_RESULTS]
    if not message:
        message = "已联网检索。" if clipped else "已联网检索，但没有找到可用的公开摘要。"
    return {
        "ok": True,
        "provider": provider,
        "query": query,
        "results": clipped,
        "offline": False,
        "empty_state": False,
        "error": "",
        "message": message,
    }


def resolve_search_settings(db: Session | None = None) -> tuple[str, str]:
    """返回 (provider, api_key)。数据库优先，其次环境变量，默认 duckduckgo。"""
    from app.config import get_settings

    env = get_settings()
    provider = (getattr(env, "web_search_provider", None) or "duckduckgo").strip().lower()
    api_key = (getattr(env, "web_search_api_key", None) or "").strip()
    if db is not None:
        try:
            from app.models import SystemSetting

            row = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
        except Exception:
            row = None
        if row is not None:
            row_provider = (getattr(row, "web_search_provider", None) or "").strip().lower()
            row_key = (getattr(row, "web_search_api_key", None) or "").strip()
            if row_provider:
                provider = row_provider
            if row_key:
                api_key = row_key
    if provider not in _PROVIDERS:
        provider = "duckduckgo"
    return provider, api_key


def _paid_empty_message(provider: str) -> str:
    label = {"tavily": "Tavily", "bing": "Bing", "serpapi": "SerpAPI"}.get(provider, provider)
    return (
        f"已选择 {label} 作为联网搜索，但没有填写 API Key。"
        "请到系统设置填写密钥，或改回「DuckDuckGo（无需密钥）」。本次没有联网检索。"
    )


def _error_message(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "联网搜索超时（约 15 秒），没有拿到公开结果。本次检索未完成。", False
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, OSError)):
        return "offline", "当前无法访问公网，联网搜索没有执行成功。请检查网络后重试。", True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else 0
        return "http", f"搜索服务返回 HTTP {code}，没有拿到可用结果。本次检索未完成。", False
    return "error", "联网搜索失败，没有拿到公开结果。本次检索未完成。", False


def _pick_search_error(errors: list[BaseException]) -> BaseException:
    """全部端点都失败时，保留真实的超时或断网原因，不把空结果说成已经搜过。"""
    timeouts = [err for err in errors if isinstance(err, httpx.TimeoutException)]
    statuses = [err for err in errors if isinstance(err, httpx.HTTPStatusError)]
    connects = [
        err for err in errors
        if isinstance(err, (httpx.ConnectError, httpx.NetworkError, OSError))
        and not isinstance(err, httpx.TimeoutException)
    ]
    if statuses and not timeouts:
        return statuses[-1]
    if timeouts and not statuses:
        return timeouts[-1]
    if connects and len(connects) == len(errors):
        return connects[-1]
    if timeouts:
        return timeouts[-1]
    return errors[-1]


async def _fetch_ddg_html(client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
    resp = await client.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query, "kl": "cn-zh"},
    )
    resp.raise_for_status()
    return parse_duckduckgo_html(resp.text)


async def _fetch_ddg_lite(client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
    resp = await client.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": query},
    )
    resp.raise_for_status()
    return parse_duckduckgo_html(resp.text)


async def _fetch_ddg_instant(client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
    resp = await client.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
    )
    resp.raise_for_status()
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        payload = {}
    return parse_duckduckgo_instant(payload if isinstance(payload, dict) else {})


async def _fetch_bing(client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
    resp = await client.get(
        "https://www.bing.com/search",
        params={"q": query, "setlang": "zh-Hans", "count": str(MAX_RESULTS)},
    )
    resp.raise_for_status()
    return parse_bing_html(resp.text)


async def _search_duckduckgo(query: str) -> list[dict[str, str]]:
    """默认无密钥检索。

    DuckDuckGo HTML / Lite / Instant 与 Bing 页面并行尝试。某个端点读超时不再中断其余端点；
    只有全部失败时才把超时或断网上报给对话。
    """

    async def attempt(fn):
        async with _httpx_client(ENDPOINT_TIMEOUT_SECONDS) as client:
            return await fn(client, query)

    jobs = (
        ("ddg", _fetch_ddg_html),
        ("ddg", _fetch_ddg_lite),
        ("ddg", _fetch_ddg_instant),
        ("bing", _fetch_bing),
    )
    task_labels: dict[asyncio.Task, str] = {}
    for label, fn in jobs:
        task_labels[asyncio.create_task(attempt(fn))] = label

    errors: list[BaseException] = []
    bing_rows: list[dict[str, str]] | None = None
    grace_deadline: float | None = None
    try:
        pending = set(task_labels)
        while pending:
            grace = None
            if bing_rows is not None and grace_deadline is not None:
                grace = max(0.0, grace_deadline - time.monotonic())
            done, pending = await asyncio.wait(
                pending,
                timeout=grace,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                if bing_rows:
                    return bing_rows
                continue
            for task in done:
                label = task_labels[task]
                exc = task.exception()
                if exc is not None:
                    errors.append(exc)
                    continue
                rows = task.result() or []
                if not rows:
                    continue
                if label == "ddg":
                    return rows
                bing_rows = rows
                if grace_deadline is None:
                    grace_deadline = time.monotonic() + _DDG_GRACE_SECONDS
            ddg_left = any(task_labels[task] == "ddg" for task in pending)
            if bing_rows and not ddg_left:
                return bing_rows
        if bing_rows:
            return bing_rows
    finally:
        for task in task_labels:
            if not task.done():
                task.cancel()
        await asyncio.gather(*task_labels, return_exceptions=True)

    if errors:
        raise _pick_search_error(errors)
    return []


async def _search_tavily(query: str, api_key: str) -> list[dict[str, str]]:
    async with _httpx_client() as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": MAX_RESULTS, "include_answer": False},
        )
        resp.raise_for_status()
        data = resp.json()
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in (data.get("results") or [])[:MAX_RESULTS]:
        _push_result(items, seen, str(row.get("title") or ""), str(row.get("url") or ""), str(row.get("content") or ""))
    return items


async def _search_bing(query: str, api_key: str) -> list[dict[str, str]]:
    async with _httpx_client() as client:
        resp = await client.get(
            "https://api.bing.microsoft.com/v7.0/search",
            params={"q": query, "count": MAX_RESULTS, "mkt": "zh-CN"},
            headers={"Ocp-Apim-Subscription-Key": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    pages = ((data.get("webPages") or {}).get("value") or [])[:MAX_RESULTS]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in pages:
        _push_result(items, seen, str(row.get("name") or ""), str(row.get("url") or ""), str(row.get("snippet") or ""))
    return items


async def _search_serpapi(query: str, api_key: str) -> list[dict[str, str]]:
    async with _httpx_client() as client:
        resp = await client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": api_key, "num": MAX_RESULTS, "hl": "zh-cn"},
        )
        resp.raise_for_status()
        data = resp.json()
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in (data.get("organic_results") or [])[:MAX_RESULTS]:
        _push_result(items, seen, str(row.get("title") or ""), str(row.get("link") or ""), str(row.get("snippet") or ""))
    return items


async def search_web(
    query: str,
    db: Session | None = None,
    *,
    provider: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    q = (query or "").strip()[:MAX_QUERY_CHARS]
    if provider is None or api_key is None:
        resolved_provider, resolved_key = resolve_search_settings(db)
        provider = provider or resolved_provider
        if api_key is None:
            api_key = resolved_key
    provider = (provider or "duckduckgo").strip().lower()
    if provider not in _PROVIDERS:
        provider = "duckduckgo"
    api_key = (api_key or "").strip()
    if not q:
        return _failure(provider=provider, query="", message="没有可检索的关键词。", error="empty_query")
    if provider in _PAID_PROVIDERS and not api_key:
        return _failure(
            provider=provider,
            query=q,
            message=_paid_empty_message(provider),
            error="empty_key",
            empty_state=True,
        )
    try:
        if provider == "tavily":
            results = await _search_tavily(q, api_key)
        elif provider == "bing":
            results = await _search_bing(q, api_key)
        elif provider == "serpapi":
            results = await _search_serpapi(q, api_key)
        else:
            provider = "duckduckgo"
            results = await _search_duckduckgo(q)
    except Exception as exc:
        error, message, offline = _error_message(exc)
        return _failure(provider=provider, query=q, message=message, error=error, offline=offline)
    return _success(provider, q, results)


async def fetch_url(url: str) -> dict[str, Any]:
    target = (url or "").strip()
    if not _is_allowed_http_url(target):
        return {
            "ok": False,
            "url": target,
            "error": "bad_url",
            "message": "只允许打开公网 http 或 https 链接，不能读取本地文件。",
            "title": "",
            "text": "",
        }
    try:
        async with _httpx_client() as client:
            async with client.stream("GET", target) as resp:
                resp.raise_for_status()
                final_url = str(resp.url)
                if not _is_allowed_http_url(final_url):
                    return {
                        "ok": False,
                        "url": target,
                        "error": "bad_url",
                        "message": "链接跳转到了不允许访问的地址，已中止。",
                        "title": "",
                        "text": "",
                    }
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    room = MAX_FETCH_BYTES - total
                    if room <= 0:
                        break
                    chunks.append(chunk[:room])
                    total += len(chunk[:room])
                    if total >= MAX_FETCH_BYTES:
                        break
                encoding = resp.encoding or "utf-8"
        raw = b"".join(chunks).decode(encoding, errors="replace")
    except Exception as exc:
        error, message, _offline = _error_message(exc)
        return {"ok": False, "url": target, "error": error, "message": message, "title": "", "text": ""}
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = _clip(strip_html(title_match.group(1) if title_match else ""), 160) or final_url
    text = _clip(strip_html(raw), 4000)
    return {
        "ok": True,
        "url": final_url,
        "title": title,
        "text": text,
        "error": "",
        "message": "已打开该链接。",
    }


def format_sources_block(results: list[dict[str, Any]]) -> str:
    rows = [item for item in results if item.get("url")][:MAX_RESULTS]
    if not rows:
        return ""
    lines = ["参考来源"]
    for index, item in enumerate(rows, 1):
        title = (item.get("title") or item.get("url") or "来源").strip()
        url = str(item.get("url") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        lines.append(f"{index}. {title}")
        lines.append(f"   {url}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def sources_payload(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = []
    for item in results:
        url = str(item.get("url") or "").strip()
        if not _is_allowed_http_url(url):
            continue
        payload.append({
            "title": (item.get("title") or url).strip(),
            "url": url,
            "snippet": (item.get("snippet") or "").strip(),
        })
        if len(payload) >= MAX_RESULTS:
            break
    return payload


def strip_unknown_urls(text: str, allowed: set[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;，。)")
        if url in allowed:
            return match.group(0)
        return ""

    return _URL_RE.sub(repl, text or "")


def _local_context_text(db: Session | None, workspace: dict | None, context: dict | None) -> str:
    parts: list[str] = []
    if db is not None:
        try:
            from app.models import CompanyProfile

            company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
        except Exception:
            company = None
        if company is not None:
            bits = [
                f"企业全称：{company.full_name or ''}",
                f"简称：{company.short_name or ''}",
                f"资质概况：{(company.qual_overview or '')[:400]}",
                f"典型项目：{(company.typical_projects or '')[:400]}",
            ]
            parts.append("\n".join(bit for bit in bits if not bit.endswith("：")))
        try:
            from app.models import TenderProject
            from app.services.agent_runtime import resolve_project_id

            pid = resolve_project_id(workspace, context)
            if pid:
                project = db.query(TenderProject).filter(TenderProject.id == pid).first()
                if project is not None:
                    fields = project.fields or {}
                    parts.append(
                        "当前项目："
                        + json.dumps(
                            {
                                "title": project.title,
                                "tenderer": fields.get("tenderer") or "",
                                "project_name": fields.get("project_name") or "",
                            },
                            ensure_ascii=False,
                        )
                    )
                    from app.services.agent_capabilities import memo_prompt_block

                    memo = memo_prompt_block(fields)
                    if memo:
                        parts.append(memo)
        except Exception:
            pass
    return "\n\n".join(part for part in parts if part.strip())


def _fallback_from_snippets(question: str, results: list[dict[str, Any]]) -> str:
    lines = [f"已根据公开检索结果整理「{question[:80]}」，供编写标书时参考："]
    for index, item in enumerate(results[:MAX_RESULTS], 1):
        snippet = (item.get("snippet") or "").strip() or "（无摘要）"
        lines.append(f"{index}. {item.get('title') or '来源'}：{snippet}")
    lines.append("请结合招标文件与企业资料核对，不要直接把摘要当成投标承诺。")
    return "\n".join(lines)


async def run_web_research(
    text: str,
    db: Session | None,
    history: list[dict] | None = None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """执行联网检索（以及用户点名的单个链接），把真实来源写进回复和 metadata。"""
    from app.services import ai

    query = extract_search_query(text)
    fetch_target = explicit_fetch_url(text)
    search_result: dict[str, Any] | None = None
    fetched: dict[str, Any] | None = None
    if should_search(text, context) or not fetch_target:
        search_result = await search_web(query, db=db)
    if fetch_target:
        fetched = await fetch_url(fetch_target)

    results: list[dict[str, str]] = []
    if search_result and search_result.get("ok"):
        results.extend(search_result.get("results") or [])
    if fetched and fetched.get("ok") and fetched.get("url"):
        results.append({
            "title": fetched.get("title") or fetched["url"],
            "url": fetched["url"],
            "snippet": _clip(fetched.get("text") or "", MAX_SNIPPET_CHARS),
        })
    sources = sources_payload(results)
    allowed = {item["url"] for item in sources}
    searched = bool(search_result and search_result.get("ok"))
    failed = search_result if search_result and not search_result.get("ok") else None

    hist = []
    for message in (history or [])[-6:]:
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            hist.append({"role": role, "content": content})

    async def complete(messages: list[dict]) -> str:
        try:
            return (await ai.chat_completion(messages, db=db) or "").strip()
        except Exception:
            return ""

    local_blob = _local_context_text(db, workspace, context)
    notices: list[str] = []
    if failed:
        notices.append(str(failed.get("message") or "联网搜索没有完成。"))
    if fetched and not fetched.get("ok"):
        notices.append(str(fetched.get("message") or "链接未能打开。"))

    answer = ""
    if sources:
        packet = []
        for item in sources:
            packet.append({
                "title": item["title"],
                "url": item["url"],
                "snippet": item["snippet"],
            })
        if fetched and fetched.get("ok") and fetched.get("text"):
            packet.append({"opened_page_excerpt": _clip(fetched.get("text") or "", 1500), "url": fetched.get("url")})
        system = (
            "你是标书智能体。下面是刚刚检索到的公开资料，只能依据这些标题、摘要和摘录回答。"
            "禁止编造来源、标题或网址；正文不要自己写 URL，系统会附上真实来源。"
            "用中文说明这些资料对投标写法的参考意义，并提醒以招标文件为准。"
        )
        user = (
            f"用户问题：{text}\n\n"
            f"检索结果：\n{json.dumps(packet, ensure_ascii=False)}\n\n"
            f"本地企业/项目（可补充，不可冒充网上来源）：\n{local_blob or '无'}"
        )
        answer = await complete(
            [{"role": "system", "content": system}, *hist, {"role": "user", "content": user}],
        )
        answer = strip_unknown_urls(answer, allowed).strip()
        if not answer:
            answer = _fallback_from_snippets(query or text, sources)
        block = format_sources_block(sources)
        if block and block not in answer:
            answer = f"{answer.rstrip()}\n\n{block}"
        if notices:
            answer = f"{' '.join(notices)}\n\n{answer}"
    else:
        searched_empty = bool(search_result and search_result.get("ok") and not sources)
        system = (
            "没有可用的公开网页来源。请只根据本地企业档案和当前项目回答；"
            "不知道就说明不知道。不要编造网页、公告或网址，不要假装已经搜到了网上资料。"
        )
        user = f"用户问题：{text}\n\n本地资料：\n{local_blob or '无'}"
        local_answer = await complete(
            [{"role": "system", "content": system}, *hist, {"role": "user", "content": user}],
        )
        local_answer = strip_unknown_urls(local_answer, set()).strip()
        if not local_answer:
            if local_blob:
                local_answer = "以下仅保留本地企业/项目资料，未引用任何网页。\n\n" + local_blob
            else:
                local_answer = "当前也没有可用的企业档案或项目上下文。网络恢复后可以再说一次「联网查一下」。"
        if notices:
            notice = " ".join(notices)
        elif searched_empty:
            notice = str((search_result or {}).get("message") or "已联网检索，但没有找到可用的公开摘要。")
        else:
            notice = "本次没有拿到公开网页结果。"
        answer = f"{notice}\n\n{local_answer}"

    web_meta = search_result or {
        "ok": False,
        "provider": "",
        "query": query,
        "results": [],
        "offline": False,
        "empty_state": False,
        "error": "not_run",
        "message": "",
    }
    # 不把可选 API Key 带进对话 metadata。
    safe_web = {
        "ok": bool(web_meta.get("ok")),
        "provider": web_meta.get("provider") or "",
        "query": web_meta.get("query") or query,
        "offline": bool(web_meta.get("offline")),
        "empty_state": bool(web_meta.get("empty_state")),
        "error": web_meta.get("error") or "",
        "message": web_meta.get("message") or "",
        "searched": searched,
    }
    return {
        "answer": answer.strip(),
        "mode": "web_search" if sources else "fallback",
        "metadata": {
            "intent": "web_search",
            "web_search": safe_web,
            "sources": sources,
            "fetch_url": (
                {"ok": bool(fetched.get("ok")), "url": fetched.get("url") or fetch_target, "error": fetched.get("error") or ""}
                if fetched
                else None
            ),
            "actions": [
                {"type": "link", "label": "系统设置", "url": "/settings"},
            ],
        },
    }
