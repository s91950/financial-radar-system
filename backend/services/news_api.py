"""NewsAPI integration for fetching global news."""

import logging
from datetime import datetime, timedelta

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

NEWS_API_BASE = "https://newsapi.org/v2"


async def fetch_top_headlines(
    category: str = "business",
    country: str = "us",
    page_size: int = 20,
) -> list[dict]:
    """Fetch top headlines from NewsAPI."""
    if not settings.NEWS_API_KEY or settings.NEWS_API_KEY == "your_newsapi_key_here":
        logger.warning("NEWS_API_KEY not set, skipping NewsAPI fetch")
        return []

    params = {
        "apiKey": settings.NEWS_API_KEY,
        "category": category,
        "country": country,
        "pageSize": page_size,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{NEWS_API_BASE}/top-headlines", params=params)
            resp.raise_for_status()
            data = resp.json()
            return _normalize_articles(data.get("articles", []))
    except Exception as e:
        logger.error(f"NewsAPI top-headlines error: {e}")
        return []


async def search_news(
    query: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    language: str = "en",
    sort_by: str = "publishedAt",
    page_size: int = 20,
) -> list[dict]:
    """Search news articles by query."""
    if not settings.NEWS_API_KEY or settings.NEWS_API_KEY == "your_newsapi_key_here":
        logger.warning("NEWS_API_KEY not set, skipping NewsAPI search")
        return []

    if from_date is None:
        from_date = datetime.utcnow() - timedelta(hours=24)

    params = {
        "apiKey": settings.NEWS_API_KEY,
        "q": query,
        "from": from_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "language": language,
        "sortBy": sort_by,
        "pageSize": page_size,
    }
    if to_date:
        params["to"] = to_date.strftime("%Y-%m-%dT%H:%M:%S")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{NEWS_API_BASE}/everything", params=params)
            resp.raise_for_status()
            data = resp.json()
            return _normalize_articles(data.get("articles", []))
    except Exception as e:
        logger.error(f"NewsAPI search error: {e}")
        return []


def _normalize_articles(articles: list[dict]) -> list[dict]:
    """Normalize NewsAPI articles to our standard format."""
    results = []
    for a in articles:
        if not a.get("title") or a["title"] == "[Removed]":
            continue
        results.append({
            "title": a.get("title", ""),
            "content": a.get("content") or a.get("description", ""),
            "source": a.get("source", {}).get("name", "NewsAPI"),
            "source_url": a.get("url", ""),
            "published_at": a.get("publishedAt"),
            "category": "news",
        })
    return results
