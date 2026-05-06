"""工商時報 (Commercial Times) RSS 抓取器。

工商時報官網直接提供 RSS feed：
  https://www.ctee.com.tw/rss_web/livenews/{category}

可用 category：
  ctee     即時新聞綜合（最即時，建議用這個）
  policy   政經
  stock    證券
  finance  金融
  p-tax    產業稅務
  industry 產業
  house    房地產
  world    國際
  china    兩岸
  tech     科技
  life     生活

注意：RSS 的 <pubDate> 沒有時區標記（例：2026-05-06T11:57:13），
實際是台灣時間（UTC+8），需手動換算為 UTC 才能與 datetime.utcnow() 比較。
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
_TW_OFFSET = timezone(timedelta(hours=8))


def is_ctee_url(url: str) -> bool:
    """匹配工商時報 RSS / livenews 連結。"""
    return "ctee.com.tw/rss_web" in url or "ctee.com.tw/livenews" in url


def _parse_tw_pubdate(s: str) -> datetime | None:
    """解析工商時報 pubDate，視為台灣時間，回傳 naive UTC datetime。

    格式範例：
      2026-05-06T11:57:13
      2026-05-06 11:57:13
      Tue, 06 May 2026 11:57:13 +0800   (若改版加入時區)
    """
    if not s:
        return None
    s = s.strip()
    # 既有時區資訊的 RFC 822 格式
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt and dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError):
        pass
    # 無時區的 ISO-like 格式：視為台灣時間
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.strptime(s[:19], fmt)
            return naive.replace(tzinfo=_TW_OFFSET).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    return None


async def fetch_ctee_news(url: str, hours_back: int = 24) -> list[dict]:
    """抓取工商時報 RSS，回傳指定時間內的文章清單。

    傳入完整 RSS URL，例如 https://www.ctee.com.tw/rss_web/livenews/ctee。
    若 URL 給的是 livenews 頁面（非 rss_web），會自動轉換到對應 RSS。
    """
    from backend.services.source_health import mark_attempt
    rss_url = url
    m = re.search(r"ctee\.com\.tw/livenews/([\w-]+)", url)
    if m and "rss_web" not in url:
        rss_url = f"https://www.ctee.com.tw/rss_web/livenews/{m.group(1)}"

    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
            resp = await client.get(rss_url, headers=_HEADERS)
            resp.raise_for_status()
            xml_text = resp.text
        mark_attempt(url, success=True)
    except Exception as e:
        logger.warning(f"ctee RSS fetch error ({rss_url}): {e}")
        mark_attempt(url, success=False, error=str(e))
        return []

    feed = feedparser.parse(xml_text)
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    articles: list[dict] = []

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        pub_dt = _parse_tw_pubdate(entry.get("published") or entry.get("updated") or "")
        if pub_dt and pub_dt < cutoff:
            continue

        articles.append({
            "title": title,
            "content": (entry.get("summary") or entry.get("description") or "").strip(),
            "source": "工商時報",
            "source_url": link,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": "financial",
        })

    logger.info(f"ctee: {len(articles)} articles within {hours_back}h from {rss_url}")
    return articles
