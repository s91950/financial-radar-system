"""RSS feed parser for monitoring official sources."""

import asyncio
import logging
from datetime import datetime, timedelta

import feedparser
import httpx

logger = logging.getLogger(__name__)

# URL patterns that are known redirect wrappers (not actual article pages)
_REDIRECT_PATTERNS = (
    "feeds.reuters.com",
    "feeds.feedburner.com",
    "rss.sina.com.cn",
    "feeds.bloomberg.com",
    "feeds.a.dj.com",
    "feeds.marketwatch.com",
)


async def _resolve_redirect(url: str, client: httpx.AsyncClient) -> str:
    """Follow HTTP redirects to get the final article URL.

    Only resolves URLs that match known redirect-wrapper patterns to avoid
    unnecessary requests. Falls back to original URL on any error.
    Uses streaming GET (not HEAD) because some servers (e.g. Google News)
    only redirect on GET requests.
    """
    if not url:
        return url
    if not any(p in url for p in _REDIRECT_PATTERNS):
        return url
    try:
        async with client.stream("GET", url, follow_redirects=True, timeout=8) as resp:
            final = str(resp.url)
        # Sanity check: resolved URL should be http(s) and different from original
        if final.startswith("http") and final != url:
            return final
    except Exception:
        pass
    return url


async def fetch_rss_feed(url: str, hours_back: int = 24) -> list[dict]:
    """Fetch and parse an RSS feed, returning recent entries."""
    try:
        async with httpx.AsyncClient(timeout=30, verify=False, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FinancialRadar/1.0)"})
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

        cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        articles = []

        for entry in feed.entries:
            published = _parse_date(entry)
            if published and published < cutoff:
                continue

            articles.append({
                "title": entry.get("title", "No title"),
                "content": _get_content(entry),
                "source": feed.feed.get("title", url),
                "source_url": entry.get("link", ""),
                "published_at": published.isoformat() if published else None,
                "category": "official",
            })

        # Resolve redirect URLs concurrently (only for known redirect patterns)
        if articles:
            async with httpx.AsyncClient(timeout=10, verify=False, follow_redirects=True) as resolve_client:
                resolved = await asyncio.gather(
                    *[_resolve_redirect(a["source_url"], resolve_client) for a in articles],
                    return_exceptions=True,
                )
            for i, r in enumerate(resolved):
                if isinstance(r, str):
                    articles[i]["source_url"] = r

        return articles
    except Exception as e:
        logger.error(f"RSS feed error ({url}): {e}")
        return []


async def fetch_multiple_feeds(
    feeds: list[dict],
    hours_back: int = 24,
    global_topics: list[str] | None = None,
) -> list[dict]:
    """Fetch multiple RSS feeds and combine results.

    feeds: list of {"name": str, "url": str, "keywords": list[str]}
    global_topics: fallback radar topic strings used when a feed has no source-specific keywords.
                   Each topic may use boolean AND/OR syntax: "(A OR B) C" means A-or-B AND C.
                   An article passes the fallback filter if it matches ANY topic.
    """
    all_articles = []
    for feed_info in feeds:
        articles = await fetch_rss_feed(feed_info["url"], hours_back)
        source_kws = feed_info.get("keywords", [])
        if source_kws:
            # Source-specific keywords: simple OR matching (user enters plain keyword list)
            articles = _filter_by_keywords(articles, source_kws)
        elif global_topics:
            # No source keywords — filter against radar topics with proper boolean semantics
            articles = _filter_by_topic_strings(articles, global_topics)
        else:
            # 無任何過濾條件 → 不納入，避免無關文章進入雷達
            articles = []
        all_articles.extend(articles)
    return all_articles


def _filter_by_topic_strings(articles: list[dict], topics: list[str]) -> list[dict]:
    """Filter articles against radar topic strings, preserving boolean AND/OR semantics.

    Each topic may be:
      - A plain keyword: "台股"  →  matches if "台股" appears in the text
      - A boolean group: "(Fed OR FOMC) 升息"  →  matches if (Fed or FOMC) AND 升息 appear

    An article passes if it matches ANY topic in the list.
    """
    import re as _re

    def _parse_topic_groups(topic: str) -> list[list[str]]:
        """Parse a topic string into AND-groups of OR-terms."""
        raw_groups = _re.findall(r'\(([^)]+)\)', topic)
        if raw_groups:
            groups: list[list[str]] = []
            for raw in raw_groups:
                terms = [t.strip().strip("\"'") for t in _re.split(r'\bOR\b', raw, flags=_re.IGNORECASE)]
                terms = [t for t in terms if t]
                if terms:
                    groups.append(terms)
            # Bare words outside parentheses are also AND conditions
            bare = _re.sub(r'\([^)]+\)', '', topic)
            bare = _re.sub(r'\b(?:OR|AND)\b', ' ', bare, flags=_re.IGNORECASE)
            for word in bare.split():
                word = word.strip().strip("\"'")
                if word:
                    groups.append([word])
            return groups if groups else [[topic]]
        # Simple topic: single term
        return [[topic]]

    def _matches_topic(text: str, topic: str) -> bool:
        groups = _parse_topic_groups(topic)
        tl = text.lower()
        return all(any(term.lower() in tl for term in group) for group in groups)

    filtered = []
    for article in articles:
        text = f"{article.get('title', '')} {article.get('content', '')}".lower()
        for topic in topics:
            if _matches_topic(text, topic):
                filtered.append({**article, "matched_keyword": topic})
                break
    return filtered


def _filter_by_keywords(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Filter articles that contain any of the specified keywords.
    Sets matched_keyword on each passing article for downstream severity assessment.
    """
    filtered = []
    for article in articles:
        text = f"{article.get('title', '')} {article.get('content', '')}".lower()
        for kw in keywords:
            if kw.lower() in text:
                filtered.append({**article, "matched_keyword": kw})
                break
    return filtered


def _parse_date(entry) -> datetime | None:
    """Parse published date from RSS entry.

    feedparser returns published_parsed as UTC struct_time.
    calendar.timegm() treats input as UTC (unlike mktime which assumes local time),
    so the result is comparable with datetime.utcnow().
    """
    import calendar
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.utcfromtimestamp(calendar.timegm(parsed))
            except Exception:
                continue
    return None


def _get_content(entry) -> str:
    """Extract content from RSS entry."""
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    return entry.get("summary", entry.get("description", ""))
