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

_GN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ---------------------------------------------------------------------------
# Google News URL 解碼：CBMi... article ID → 真正的文章 URL
# 原理：從 Google News 文章頁取得簽名 + 時間戳，再透過 batchexecute API 解碼
# ---------------------------------------------------------------------------

_DECODE_CONCURRENCY = 5  # 同時取得解碼參數的併發上限


async def _get_decode_params(
    client: httpx.AsyncClient, gn_art_id: str
) -> dict | None:
    """從 Google News 文章頁取得解碼用的 signature 和 timestamp。"""
    try:
        resp = await client.get(
            f"https://news.google.com/rss/articles/{gn_art_id}",
            follow_redirects=True,
            timeout=10,
        )
        html = resp.text
        sig_m = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts_m = re.search(r'data-n-a-ts="([^"]+)"', html)
        if sig_m and ts_m:
            return {
                "gn_art_id": gn_art_id,
                "signature": sig_m.group(1),
                "timestamp": int(ts_m.group(1)),
            }
    except Exception:
        pass
    return None


async def _batch_decode(
    client: httpx.AsyncClient, params_list: list[dict]
) -> list[str | None]:
    """透過 Google batchexecute API 批次解碼多個 article ID → 真正 URL。"""
    if not params_list:
        return []

    articles_reqs = []
    for p in params_list:
        articles_reqs.append([
            "Fbv4je",
            json.dumps([
                "garturlreq",
                [["X", "X", ["X", "X"], None, None, 1, 1, "US:en",
                  None, 1, None, None, None, None, None, 0, 1],
                 "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                p["gn_art_id"], p["timestamp"], p["signature"],
            ]),
        ])

    payload = f"f.req={quote(json.dumps([articles_reqs]))}"
    try:
        resp = await client.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data=payload,
            timeout=15,
        )
        resp.raise_for_status()

        decoded_urls: list[str | None] = [None] * len(params_list)
        text = resp.text
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith("[["):
                continue
            try:
                parsed = json.loads(line)
                idx = 0
                for item in parsed:
                    if (isinstance(item, list) and len(item) >= 3
                            and item[0] == "wrb.fr"):
                        try:
                            inner = json.loads(item[2])
                            if isinstance(inner, list) and len(inner) >= 2:
                                decoded_urls[idx] = inner[1]
                        except Exception:
                            pass
                        idx += 1
            except json.JSONDecodeError:
                pass
        return decoded_urls
    except Exception as e:
        logger.debug(f"batchexecute failed: {e}")
        return [None] * len(params_list)


async def _resolve_google_news_urls(
    client: httpx.AsyncClient, article_ids: list[str]
) -> list[str | None]:
    """解碼一批 Google News article ID 為真正的文章 URL。

    流程：並行取得每個 article 的 signature/timestamp → 批次呼叫 batchexecute
    失敗的 URL 返回 None（caller 可 fallback）。
    """
    if not article_ids:
        return []

    # Step 1: 並行取得解碼參數（限制併發）
    sem = asyncio.Semaphore(_DECODE_CONCURRENCY)

    async def _get_with_sem(art_id: str):
        async with sem:
            return await _get_decode_params(client, art_id)

    params_results = await asyncio.gather(
        *[_get_with_sem(aid) for aid in article_ids],
        return_exceptions=True,
    )

    # 分離成功與失敗
    valid_params = []
    idx_map = {}  # valid_params index → original index
    for i, p in enumerate(params_results):
        if isinstance(p, dict):
            idx_map[len(valid_params)] = i
            valid_params.append(p)

    # Step 2: 批次解碼
    decoded = await _batch_decode(client, valid_params)

    # Step 3: 映射回原始順序
    result: list[str | None] = [None] * len(article_ids)
    for vi, url in enumerate(decoded):
        if url and vi in idx_map:
            result[idx_map[vi]] = url

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

                raw_entries.append({
                    "title": title,
                    "content": _clean_html(entry.get("summary", entry.get("description", ""))),
                    "source": source or entry.get("source", {}).get("title", "Google News"),
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
                    # fallback: Google News 可點擊連結
                    source_url = entry_data["raw_link"].replace("/rss/articles/", "/articles/")
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
