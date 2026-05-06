"""NOWnews 今日新聞 Google News Sitemap scraper.

NowNews 沒有公開 RSS feed，但提供 Google News Sitemap：
  https://www.nownews.com/newsSitemap-daily.xml

格式為標準 Google News Sitemap，每篇文章在 XML 內已含：
  <loc>             文章 URL
  <news:title>      標題
  <news:publication_date> 發布時間 (ISO 8601 含時區)
  <lastmod>         最後修改時間（含 +08:00）

不需要 fetch 每篇文章頁面，比起 GN 代理（site:nownews.com）即時得多
（sitemap 通常 5-15 分鐘內更新；GN 索引延遲常達 1-3 小時）。
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

NOWNEWS_NEWS_SITEMAP = "https://www.nownews.com/newsSitemap-daily.xml"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FeedFetcher/1.0)"}


def is_nownews_url(url: str) -> bool:
    """匹配 NowNews sitemap 連結。"""
    return "nownews.com" in url and "sitemap" in url.lower()


async def fetch_nownews_news(hours_back: int = 24) -> list[dict]:
    """解析 NowNews Google News Sitemap，回傳指定時間內的文章清單。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True, verify=False) as client:
            r = await client.get(NOWNEWS_NEWS_SITEMAP)
            r.raise_for_status()
            content = r.text
        mark_attempt(NOWNEWS_NEWS_SITEMAP, success=True)
    except Exception as e:
        logger.warning(f"nownews sitemap fetch error: {e}")
        mark_attempt(NOWNEWS_NEWS_SITEMAP, success=False, error=str(e))
        return []

    entries = re.findall(r"<url>(.*?)</url>", content, re.DOTALL)
    articles: list[dict] = []

    for entry in entries:
        loc_m = re.search(r"<loc>([^<]+)</loc>", entry)
        title_m = re.search(r"<news:title>(?:<!\[CDATA\[)?([^\]<]+)", entry)
        date_m = re.search(r"<news:publication_date>([^<]+)</news:publication_date>", entry)

        if not loc_m or not date_m or not title_m:
            continue

        try:
            pub_dt = datetime.fromisoformat(date_m.group(1).strip())
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
        except Exception:
            continue

        title = title_m.group(1).strip()
        if not title:
            continue

        articles.append({
            "title": title,
            "source": "NOWnews今日新聞",
            "source_url": loc_m.group(1).strip(),
            "content": "",
            "published_at": pub_dt.astimezone(timezone.utc).isoformat(),
            "category": "radar",
        })

    logger.info(f"nownews: {len(articles)} articles within {hours_back}h")
    return articles
