"""Yahoo Finance RSS 抓取器（多 ticker 並發合併版）。

Yahoo Finance 的 sitewide RSS（`finance.yahoo.com/rss/topstories`、`/news/rssindex`）
在 2026-05 觀察到最新 pubDate 卡在 2-3 天前不更新，但 ticker-symbol headline feed
`feeds.finance.yahoo.com/rss/2.0/headline?s=<ticker>` 仍是分鐘級新鮮度。

策略：對一組代表大盤的 ticker 並發抓取，每個 feed 最多 20 篇，按 URL+title 去重後合併。
預設 ticker 涵蓋三大指數 + 兩支大型 ETF + 幾支權值股，總 unique 約 100-130 篇。

DB 內 MonitorSource.url 預期格式：
  https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC,SPY,QQQ,AAPL,TSLA,NVDA

scraper 從 query string `s=` 解析 ticker 列表；若 URL 不含 query 則 fallback 預設值。
"""
import asyncio
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
_CONCURRENCY = 4
_PER_TICKER_TIMEOUT = 12.0


def is_yahoo_url(url: str) -> bool:
    """匹配 Yahoo Finance feeds API 或 Yahoo Finance 列表頁 URL（後者會解析 ticker 後改打 feeds API）。"""
    if not url:
        return False
    return "feeds.finance.yahoo.com" in url or "finance.yahoo.com/topic/latest-news" in url


def _parse_tickers(url: str) -> list[str]:
    try:
        qs = parse_qs(urlparse(url).query)
        s = qs.get("s", [""])[0]
        if s:
            return [t.strip() for t in s.split(",") if t.strip()]
    except Exception:
        pass
    return list(_DEFAULT_TICKERS)


def _parse_pubdate(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s.strip())
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (TypeError, ValueError, IndexError):
        return None


async def _fetch_one(client: httpx.AsyncClient, ticker: str) -> list[dict]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=_PER_TICKER_TIMEOUT)
        resp.raise_for_status()
        xml_text = resp.text
    except Exception as e:
        logger.warning(f"yahoo feed fetch error (s={ticker}): {e}")
        return []

    feed = feedparser.parse(xml_text)
    out: list[dict] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        pub_dt = _parse_pubdate(entry.get("published") or entry.get("updated") or "")
        out.append({
            "title": title,
            "content": (entry.get("summary") or entry.get("description") or "").strip(),
            "source": "Yahoo Finance",
            "source_url": link,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": "financial",
        })
    return out


async def fetch_yahoo_news(url: str, hours_back: int = 24) -> list[dict]:
    """並發抓多個 ticker headline feed，按 URL+title 去重後回傳指定時間內的文章。"""
    from backend.services.source_health import mark_attempt

    tickers = _parse_tickers(url)
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)

    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def _wrapped(t: str) -> list[dict]:
            async with sem:
                return await _fetch_one(client, t)

        results = await asyncio.gather(*[_wrapped(t) for t in tickers], return_exceptions=True)

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
        mark_attempt(url, success=False, error=last_err or "all ticker feeds failed")

    articles.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    logger.info(f"yahoo: {len(articles)} unique articles within {hours_back}h from {len(tickers)} tickers")
    return articles
