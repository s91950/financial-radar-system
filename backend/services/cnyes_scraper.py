"""鉅亨網 (Cnyes) 新聞 JSON API 抓取器。

鉅亨網已停用公開 RSS feed，改以 JSON API 提供新聞：
  GET https://api.cnyes.com/media/api/v1/newslist/category/{category}

支援的分類代碼：
  tw_stock  台股
  us_stock  美股
  macro     總經
  forex     外匯
  global    國際
  crypto    加密貨幣
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://news.cnyes.com/",
    "Accept": "application/json",
}
_API_BASE = "https://api.cnyes.com/media/api/v1/newslist/category/"


def is_cnyes_api_url(url: str) -> bool:
    """Check whether a URL is a 鉅亨網 JSON API endpoint."""
    return "api.cnyes.com/media/api/v1/newslist" in url


async def fetch_cnyes_from_url(url: str, hours_back: int = 24) -> list[dict]:
    """Fetch news articles from a 鉅亨網 category API URL.

    url: e.g. https://api.cnyes.com/media/api/v1/newslist/category/tw_stock
    Returns list of article dicts in standard format.
    Requests up to 50 items to maximise coverage within the time window.
    """
    # 鉅亨網 headline/category feed 會把舊文章重新精選推上頭條，
    # publishAt 是原始發佈日期（可能是昨天或前天），不是今天入榜的時間。
    # 若用 hours_back=1 當 cutoff，昨天的精選文章全被過濾掉。
    # 改用 max(hours_back, 48h) 作底限，確保精選舊文章也能被抓取；
    # 實際去重（避免重複儲存）由 jobs.py 的 URL/title 去重機制負責。
    effective_hours = max(hours_back, 48)
    cutoff_ts = int((datetime.utcnow() - timedelta(hours=effective_hours)).timestamp())

    # 加上 limit 參數以取得更多文章（API 預設僅回傳少量）
    import urllib.parse as _up
    parsed = _up.urlparse(url)
    qs = dict(_up.parse_qsl(parsed.query))
    if "limit" not in qs and "size" not in qs:
        qs["limit"] = "100"
    fetch_url = _up.urlunparse(parsed._replace(query=_up.urlencode(qs)))

    try:
        async with httpx.AsyncClient(timeout=15, verify=False, follow_redirects=True) as client:
            resp = await client.get(fetch_url, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Cnyes API error ({url}): {e}")
        return []

    items = data.get("items", {}).get("data", [])
    articles = []
    for item in items:
        publish_ts = item.get("publishAt", 0)
        if publish_ts and publish_ts < cutoff_ts:
            continue

        title = (item.get("title") or "").strip()
        news_id = item.get("newsId")
        article_url = item.get("url") or (
            f"https://news.cnyes.com/news/id/{news_id}" if news_id else ""
        )
        summary = item.get("summary") or item.get("content") or ""

        if not title or not article_url:
            continue

        published_dt = (
            datetime.utcfromtimestamp(publish_ts).isoformat() if publish_ts else None
        )

        articles.append({
            "title": title,
            "content": summary,
            "source": "鉅亨網",
            "source_url": article_url,
            "published_at": published_dt,
            "category": "financial",
        })

    logger.debug(f"Cnyes API ({url}): fetched {len(articles)} articles")
    return articles
