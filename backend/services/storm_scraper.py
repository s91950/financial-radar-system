"""風傳媒 storm.mg Google News Sitemap scraper.

storm.mg 沒有公開 RSS feed，但有 Google News Sitemap（含標題、發布時間）。
使用 sitemap 取代 GN 代理，確保文章時間在 hours_back 內。
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

STORM_NEWS_SITEMAP = "https://www.storm.mg/sitemaps/1/article-news-1.xml"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FeedFetcher/1.0)"}


def is_storm_url(url: str) -> bool:
    return "storm.mg" in url and ("sitemap" in url or "article-news" in url)


async def fetch_storm_news(hours_back: int = 24) -> list[dict]:
    """解析風傳媒 Google News Sitemap，回傳指定時間內的文章清單。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            r = await client.get(STORM_NEWS_SITEMAP)
            r.raise_for_status()
            content = r.text
        mark_attempt(STORM_NEWS_SITEMAP, success=True)
    except Exception as e:
        logger.warning(f"storm.mg sitemap fetch error: {e}")
        mark_attempt(STORM_NEWS_SITEMAP, success=False, error=str(e))
        return []

    entries = re.findall(r"<url>(.*?)</url>", content, re.DOTALL)
    articles: list[dict] = []

    for entry in entries:
        loc_m = re.search(r"<loc>([^<]+)</loc>", entry)
        title_m = re.search(r"<news:title>(?:<!\[CDATA\[)?([^\]<]+)", entry)
        date_m = re.search(r"<news:publication_date>([^<]+)</news:publication_date>", entry)
        kw_m = re.search(r"<news:keywords>(?:<!\[CDATA\[)?([^\]<]+)", entry)

        if not loc_m or not date_m:
            continue

        try:
            pub_dt = datetime.fromisoformat(date_m.group(1).strip())
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
        except Exception:
            continue

        title = title_m.group(1).strip() if title_m else ""
        if not title:
            continue

        articles.append({
            "title": title,
            "source": "風傳媒",
            "source_url": loc_m.group(1).strip(),
            "content": kw_m.group(1).strip() if kw_m else "",
            "published_at": date_m.group(1).strip(),
            "category": "radar",
        })

    logger.info(f"storm.mg: {len(articles)} articles within {hours_back}h")
    return articles
