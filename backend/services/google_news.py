"""Google News RSS search — free, no API key needed, supports Chinese."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import quote

import feedparser
import httpx

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def _clean_source_name(source: str) -> str:
    """Clean verbose Google News source names to short publisher names.

    Examples:
      '經濟日報：不僅新聞速度 更有脈絡深度' → '經濟日報'
      '財經新聞 - 自由時報' → '自由時報'
      '"site:imf.org when:7d" - Google News' → 'Google News'
      'The New York Times' → 'The New York Times' (unchanged)
    """
    if not source:
        return source
    # Remove Google News query artifacts: "site:xxx" / "when:xxx" etc.
    if re.search(r'(?:site:|when:|inurl:)', source, re.IGNORECASE):
        # Likely a feed-level title like '"site:imf.org when:7d" - Google News'
        if "Google News" in source:
            return "Google News"
        return source
    # Truncate at Chinese/fullwidth colon + subtitle
    # e.g. "經濟日報：不僅新聞速度 更有脈絡深度" → "經濟日報"
    for sep in ('：', ':\u3000', ': '):
        idx = source.find(sep)
        if idx > 0:
            source = source[:idx].strip()
            break
    # Remove category prefix: "財經新聞 - 自由時報" → "自由時報"
    # Only if there's a " - " with a short prefix (≤6 chars, likely a category)
    if ' - ' in source:
        parts = source.split(' - ', 1)
        prefix, name = parts[0].strip(), parts[1].strip()
        if len(prefix) <= 8 and name:
            source = name
    return source.strip()

_GN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ---------------------------------------------------------------------------
# Google News URL 解碼：CBMi... article ID → 真正的文章 URL
# 方法 1（主要）：base64 解碼 protobuf 結構，直接提取嵌入的 URL — 無網路請求
# 方法 2（備援）：逐個 HTTP GET follow redirect — 慢但可靠
# ---------------------------------------------------------------------------

_DECODE_CONCURRENCY = 8


def _decode_gn_article_id(article_id: str) -> str | None:
    """從 Google News article ID (base64 protobuf) 直接提取原始 URL。

    GN article ID 是 base64url 編碼的 protobuf 結構，
    內含原始文章 URL 作為 length-delimited string。
    此方法不需要任何網路請求。
    """
    import base64

    try:
        # 補齊 base64 padding
        padded = article_id + "=" * (4 - len(article_id) % 4)
        # 嘗試 URL-safe 和標準 base64
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                raw = decoder(padded)
                break
            except Exception:
                continue
        else:
            return None

        # 在解碼的 bytes 中搜尋 URL
        url_match = re.search(rb'https?://[^\x00-\x1f\x7f-\xff\s]+', raw)
        if url_match:
            url = url_match.group(0).decode('ascii', errors='ignore')
            # 確保是完整的 URL（不是截斷的）
            if '.' in url and len(url) > 10:
                return url
    except Exception:
        pass
    return None


async def _resolve_single_gn_url(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, article_id: str
) -> str | None:
    """HTTP 備援：透過 follow redirect 解碼單個 GN article URL。"""
    async with sem:
        try:
            resp = await client.get(
                f"https://news.google.com/rss/articles/{article_id}",
                follow_redirects=True,
                timeout=10,
            )
            final = str(resp.url)
            if final.startswith("http") and "news.google.com" not in final:
                return final
        except Exception:
            pass
    return None


async def _resolve_google_news_urls(
    client: httpx.AsyncClient, article_ids: list[str]
) -> list[str | None]:
    """解碼一批 Google News article ID 為真正的文章 URL。

    優先用 base64 protobuf 解碼（無網路請求、每個 ID 獨立解碼不會混淆）。
    失敗的再用 HTTP redirect 逐個解碼。
    """
    if not article_ids:
        return []

    result: list[str | None] = [None] * len(article_ids)

    # Step 1: base64 protobuf 直接解碼（主要方法）
    need_http: list[int] = []
    for i, aid in enumerate(article_ids):
        url = _decode_gn_article_id(aid)
        if url:
            result[i] = url
        else:
            need_http.append(i)

    decoded_count = len(article_ids) - len(need_http)
    if need_http:
        logger.debug(f"GN base64 decoded {decoded_count}/{len(article_ids)}, "
                      f"{len(need_http)} need HTTP fallback")

    # Step 2: HTTP redirect 備援（僅對 base64 失敗的）
    if need_http:
        sem = asyncio.Semaphore(_DECODE_CONCURRENCY)
        fallback_results = await asyncio.gather(
            *[_resolve_single_gn_url(client, sem, article_ids[i]) for i in need_http],
            return_exceptions=True,
        )
        for j, idx in enumerate(need_http):
            fb = fallback_results[j]
            if isinstance(fb, str) and fb.startswith("http"):
                result[idx] = fb

    return result


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

async def search_google_news(
    query: str,
    hours_back: int = 72,
    language: str = "zh-TW",
    country: str = "TW",
    max_results: int = 30,
) -> list[dict]:
    """Search Google News via RSS feed.

    Returns articles in the same normalized format as news_api.
    Google News redirect URLs are decoded to actual article URLs.
    """
    url = f"{GOOGLE_NEWS_RSS}?q={quote(query)}&hl={language}&gl={country}&ceid={country}:{language}"

    try:
        async with httpx.AsyncClient(
            timeout=30,
            headers=_GN_HEADERS,
        ) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            cutoff = datetime.utcnow() - timedelta(hours=hours_back)
            raw_entries = []

            for entry in feed.entries[:max_results]:
                published = _parse_date(entry)
                if published and published < cutoff:
                    continue

                title = entry.get("title", "")
                source = ""
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    source = parts[1]

                raw_link = entry.get("link", "")
                gn_art_id = ""
                if raw_link and "/articles/" in raw_link:
                    gn_art_id = raw_link.split("/articles/")[-1].split("?")[0]

                # Prefer entry-level <source> element (accurate publisher name)
                # over title-based extraction (may include category prefixes)
                entry_source = entry.get("source", {}).get("title", "")
                if entry_source:
                    source = entry_source
                source = _clean_source_name(source) if source else "Google News"

                raw_entries.append({
                    "title": title,
                    "content": _clean_html(entry.get("summary", entry.get("description", ""))),
                    "source": source,
                    "raw_link": raw_link,
                    "gn_art_id": gn_art_id,
                    "published_at": published.isoformat() if published else None,
                    "category": "news",
                })

            # 批次解碼 Google News article IDs → 真正的文章 URL
            gn_ids = [e["gn_art_id"] for e in raw_entries]
            has_gn = any(gn_ids)
            decoded_urls = []
            if has_gn:
                try:
                    decoded_urls = await _resolve_google_news_urls(client, gn_ids)
                except Exception as e:
                    logger.warning(f"URL decode batch failed: {e}")
                    decoded_urls = [None] * len(gn_ids)

            articles = []
            for i, entry_data in enumerate(raw_entries):
                # 優先使用解碼後的真正 URL
                resolved = decoded_urls[i] if i < len(decoded_urls) else None
                if resolved:
                    source_url = resolved
                elif entry_data["gn_art_id"]:
                    # fallback: 保留原始 /rss/articles/ 連結（/articles/ 版本可能顯示錯誤頁面）
                    source_url = entry_data["raw_link"]
                else:
                    source_url = entry_data["raw_link"]

                articles.append({
                    "title": entry_data["title"],
                    "content": entry_data["content"],
                    "source": entry_data["source"],
                    "source_url": source_url,
                    "published_at": entry_data["published_at"],
                    "category": entry_data["category"],
                })

        resolved_count = sum(1 for u in decoded_urls if u) if decoded_urls else 0
        logger.info(
            f"Google News search '{query}': {len(articles)} articles, "
            f"{resolved_count}/{len(raw_entries)} URLs decoded"
        )
        return articles
    except Exception as e:
        logger.error(f"Google News RSS search error: {e}")
        return []


def _parse_date(entry) -> datetime | None:
    """Parse published date from RSS entry."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(parsed))
            except Exception:
                continue
    return None


def _clean_html(text: str) -> str:
    """Remove HTML tags from content."""
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.strip()
