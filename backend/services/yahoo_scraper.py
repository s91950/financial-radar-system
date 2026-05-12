"""Yahoo Finance / Yahoo News 多端點並發抓取器。

Yahoo 的「總覽級」RSS（`finance.yahoo.com/rss/topstories`、`news.yahoo.com/rss/topstories`、
`finance.yahoo.com/news/rssindex`）在 2026-05 觀察到 pubDate 落後實際時間 12 小時到 3 天。
但「子分類級」feeds 仍是分鐘級新鮮度：

- Yahoo Finance：`feeds.finance.yahoo.com/rss/2.0/headline?s=<ticker>&region=US&lang=en-US`
  每個 ticker 20 篇，涵蓋 Reuters / Motley Fool / Bloomberg / Barron's 等聚合。
- Yahoo News：`news.yahoo.com/rss/<category>`（world / us / business / tech 等）
  每個 category 5 篇但都在 30 分鐘內。

策略：對一組代表大盤的 ticker / 一組關鍵 category 並發抓取，按 (URL, title) 去重後合併。

DB 內 MonitorSource.url 預期格式：
  Finance: https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC,SPY,QQQ,AAPL,TSLA,NVDA&region=US&lang=en-US
  News:    https://news.yahoo.com/rss/multi?c=world,us,business,tech

`multi` 是約定識別字（非真實 endpoint），實際 HTTP 打的是各 category 個別 URL。
從 query 解析 ticker / category 列表；無 query 時 fallback 預設。
"""
import asyncio
import calendar
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, parse_qs

import feedparser
import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_DEFAULT_TICKERS = ["^GSPC", "^DJI", "^IXIC", "SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
_DEFAULT_NEWS_CATEGORIES = ["world", "us", "business", "tech"]
_CONCURRENCY = 4
_PER_FEED_TIMEOUT = 12.0


def is_yahoo_url(url: str) -> bool:
    """匹配本 scraper 處理的 Yahoo URL（Finance ticker feeds / News category feeds / 列表頁約定別名）。"""
    if not url:
        return False
    return (
        "feeds.finance.yahoo.com" in url
        or "finance.yahoo.com/topic/latest-news" in url
        or "news.yahoo.com/rss" in url
    )


def _is_news_mode(url: str) -> bool:
    return "news.yahoo.com" in url


def _parse_list_query(url: str, key: str) -> list[str]:
    try:
        qs = parse_qs(urlparse(url).query)
        v = qs.get(key, [""])[0]
        if v:
            return [t.strip() for t in v.split(",") if t.strip()]
    except Exception:
        pass
    return []


def _parse_pubdate(s: str) -> datetime | None:
    """支援 RFC 822（Yahoo Finance ticker feeds）與 ISO 8601（Yahoo News category feeds）。"""
    if not s:
        return None
    s = s.strip()
    # RFC 822: "Tue, 12 May 2026 08:12:00 +0000"
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
    except (TypeError, ValueError, IndexError):
        pass
    # ISO 8601: "2026-05-12T08:23:31Z" / "2026-05-12T08:23:31+00:00"
    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _entry_pubdate(entry) -> datetime | None:
    """從 feedparser entry 取出 UTC naive datetime。優先 published_parsed（已解析 struct_time）。"""
    pp = entry.get("published_parsed") or entry.get("updated_parsed")
    if pp:
        try:
            return datetime.utcfromtimestamp(calendar.timegm(pp))
        except (TypeError, ValueError, OverflowError):
            pass
    return _parse_pubdate(entry.get("published") or entry.get("updated") or "")


async def _fetch_feed(client: httpx.AsyncClient, feed_url: str, source_name: str, category: str) -> list[dict]:
    try:
        resp = await client.get(feed_url, headers=_HEADERS, timeout=_PER_FEED_TIMEOUT)
        resp.raise_for_status()
        xml_text = resp.text
    except Exception as e:
        logger.warning(f"yahoo feed fetch error ({feed_url}): {e}")
        return []

    feed = feedparser.parse(xml_text)
    out: list[dict] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        pub_dt = _entry_pubdate(entry)
        out.append({
            "title": title,
            "content": (entry.get("summary") or entry.get("description") or "").strip(),
            "source": source_name,
            "source_url": link,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": category,
        })
    return out


async def fetch_yahoo_news(url: str, hours_back: int = 24) -> list[dict]:
    """並發抓多端點，按 URL+title 去重後回傳指定時間內的文章。

    URL 含 news.yahoo.com → Yahoo News 多 category 模式；否則走 Yahoo Finance 多 ticker 模式。
    """
    from backend.services.source_health import mark_attempt

    is_news = _is_news_mode(url)
    if is_news:
        items = _parse_list_query(url, "c") or list(_DEFAULT_NEWS_CATEGORIES)
        feed_urls = [(f"https://news.yahoo.com/rss/{c}", c) for c in items]
        source_name = "Yahoo News"
        article_category = "news"
    else:
        items = _parse_list_query(url, "s") or list(_DEFAULT_TICKERS)
        feed_urls = [
            (f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US", t)
            for t in items
        ]
        source_name = "Yahoo Finance"
        article_category = "financial"

    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def _wrapped(feed_url: str, tag: str) -> list[dict]:
            async with sem:
                return await _fetch_feed(client, feed_url, source_name, article_category)

        results = await asyncio.gather(
            *[_wrapped(fu, tag) for fu, tag in feed_urls],
            return_exceptions=True,
        )

    any_ok = False
    last_err = None
    seen: set[tuple[str, str]] = set()
    articles: list[dict] = []
    for res in results:
        if isinstance(res, Exception):
            last_err = str(res)
            continue
        any_ok = True
        for a in res:
            key = (a["source_url"], a["title"])
            if key in seen:
                continue
            seen.add(key)
            pub_dt = None
            if a.get("published_at"):
                try:
                    pub_dt = datetime.fromisoformat(a["published_at"])
                except ValueError:
                    pub_dt = None
            if pub_dt and pub_dt < cutoff:
                continue
            articles.append(a)

    if any_ok:
        mark_attempt(url, success=True)
    else:
        mark_attempt(url, success=False, error=last_err or "all sub-feeds failed")

    articles.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    logger.info(
        f"yahoo[{'news' if is_news else 'finance'}]: {len(articles)} unique articles "
        f"within {hours_back}h from {len(feed_urls)} sub-feeds"
    )
    return articles
