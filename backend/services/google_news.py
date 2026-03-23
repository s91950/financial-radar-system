"""Google News RSS search — free, no API key needed, supports Chinese."""

import logging
from datetime import datetime, timedelta
from urllib.parse import quote

import feedparser
import httpx

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


async def search_google_news(
    query: str,
    hours_back: int = 72,
    language: str = "zh-TW",
    country: str = "TW",
    max_results: int = 30,
) -> list[dict]:
    """Search Google News via RSS feed.

    Returns articles in the same normalized format as news_api.
    """
    params = {
        "q": query,
        "hl": language,
        "gl": country,
        "ceid": f"{country}:{language}",
    }

    url = f"{GOOGLE_NEWS_RSS}?q={quote(query)}&hl={language}&gl={country}&ceid={country}:{language}"

    try:
        async with httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        ) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

        cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        articles = []

        for entry in feed.entries[:max_results]:
            published = _parse_date(entry)
            if published and published < cutoff:
                continue

            # Google News wraps source in the title: "Title - Source"
            title = entry.get("title", "")
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0]
                source = parts[1]

            articles.append({
                "title": title,
                "content": _clean_html(entry.get("summary", entry.get("description", ""))),
                "source": source or entry.get("source", {}).get("title", "Google News"),
                "source_url": entry.get("link", ""),
                "published_at": published.isoformat() if published else None,
                "category": "news",
            })

        logger.info(f"Google News search '{query}': found {len(articles)} articles")
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
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.strip()
