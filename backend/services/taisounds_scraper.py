"""太報 taisounds.com sitemap-based scraper.

太報沒有 RSS feed，但有標準 sitemap（含 lastmod 時間）。
從 sitemap 篩出 hours_back 內的文章 URL，再並行抓各頁面的 og:title / og:description。
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

TAISOUNDS_SITEMAP = "https://www.taisounds.com/sitemap.xml"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_MAX_ARTICLES = 40   # 單次最多抓幾篇（避免過多 HTTP 請求）
_CONCURRENCY = 6     # 並行抓頁面數


def is_taisounds_url(url: str) -> bool:
    return "taisounds.com" in url


async def fetch_taisounds_news(hours_back: int = 24) -> list[dict]:
    """解析太報 sitemap，回傳指定時間內的文章清單。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            r = await client.get(TAISOUNDS_SITEMAP)
            r.raise_for_status()
            content = r.text
        mark_attempt(TAISOUNDS_SITEMAP, success=True)
    except Exception as e:
        logger.warning(f"taisounds sitemap fetch error: {e}")
        mark_attempt(TAISOUNDS_SITEMAP, success=False, error=str(e))
        return []

    # 解析 sitemap 找近期文章 URL
    entries = re.findall(r"<url>(.*?)</url>", content, re.DOTALL)
    recent: list[tuple[str, str]] = []  # (url, lastmod)

    for entry in entries:
        loc_m = re.search(r"<loc>([^<]+)</loc>", entry)
        mod_m = re.search(r"<lastmod>([^<]+)</lastmod>", entry)
        if not loc_m or not mod_m:
            continue
        try:
            mod_dt = datetime.fromisoformat(mod_m.group(1).strip())
            if mod_dt.tzinfo is None:
                mod_dt = mod_dt.replace(tzinfo=timezone.utc)
            if mod_dt >= cutoff:
                recent.append((loc_m.group(1).strip(), mod_m.group(1).strip()))
        except Exception:
            continue

    # 只抓 sitemap 最前面（最新）的文章，避免過多請求
    recent = recent[:_MAX_ARTICLES]

    if not recent:
        logger.info(f"taisounds: no articles within {hours_back}h")
        return []

    # 並行抓頁面取標題
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch_article(url: str, pub_at: str) -> dict | None:
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=10, headers=_HEADERS, follow_redirects=True) as client:
                    r = await client.get(url)
                    r.raise_for_status()
                    html = r.text
            except Exception:
                return None

        # 取標題（優先 og:title）
        title_m = re.search(r'property="og:title"\s+content="([^"]{5,200})"', html)
        if not title_m:
            title_m = re.search(r'<title>([^<]{5,150})</title>', html)
        if not title_m:
            return None

        title = re.sub(r'\s*[\|｜]\s*.*?太報.*$', '', title_m.group(1)).strip()
        title = re.sub(r'\s*-\s*太報\s*TaiSounds.*$', '', title).strip()
        if not title or len(title) < 5:
            return None

        # og:description 做為內文摘要
        desc_m = re.search(r'property="og:description"\s+content="([^"]{10,400})"', html)
        content = desc_m.group(1).strip() if desc_m else ""

        return {
            "title": title,
            "source": "太報",
            "source_url": url,
            "content": content,
            "published_at": pub_at,
            "category": "radar",
        }

    results = await asyncio.gather(*[fetch_article(url, pub_at) for url, pub_at in recent])
    articles = [a for a in results if a]

    logger.info(f"taisounds: {len(articles)} articles within {hours_back}h")
    return articles
