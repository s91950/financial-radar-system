"""World Bank News JSON API scraper.

Uses the public search API:
  GET https://search.worldbank.org/api/v2/news?format=json&rows=N&os=0

Response format:
  {
    "total": int,
    "documents": {
      "0": {"title": {"cdata!": "..."}, "url": "...", "lnchdt": "ISO datetime", "descr": {"cdata!": "..."}, ...},
      ...
    }
  }

Fields may be plain strings or {"cdata!": "..."} wrappers — _cdata() handles both.
"""

import logging
from datetime import datetime, timedelta
from html import unescape

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://search.worldbank.org/api/v2/news"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FinancialRadar/1.0)",
    "Accept": "application/json",
}


def _cdata(val) -> str:
    """Extract text from a cdata wrapper or plain string."""
    if isinstance(val, dict):
        return val.get("cdata!", "")
    return str(val) if val else ""


def is_worldbank_api_url(url: str) -> bool:
    """Check whether a URL is a World Bank search API endpoint."""
    return "search.worldbank.org/api" in url


async def fetch_worldbank_news(url: str | None = None, hours_back: int = 48) -> list[dict]:
    """Fetch news from the World Bank search API.

    Returns list of article dicts in standard format.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)

    fetch_url = url or f"{_API_URL}?format=json&rows=50&os=0"
    # Ensure format=json is in the URL
    if "format=json" not in fetch_url:
        sep = "&" if "?" in fetch_url else "?"
        fetch_url += f"{sep}format=json"

    # API 有時會回傳 500，嘗試重試一次（去掉 lang_exact 參數降低失敗率）
    data = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
                resp = await client.get(fetch_url, headers=_HEADERS)
                resp.raise_for_status()
                data = resp.json()
                break
        except Exception as e:
            if attempt == 0 and "lang_exact" in fetch_url:
                # 去掉 lang_exact 參數重試
                import re
                fetch_url = re.sub(r'[&?]lang_exact=[^&]*', '', fetch_url)
                logger.debug(f"World Bank API retry without lang_exact: {fetch_url}")
                continue
            logger.error(f"World Bank API error ({fetch_url}): {e}")
            return []

    if data is None:
        return []

    documents = data.get("documents", {})
    articles = []

    for key, item in documents.items():
        if not isinstance(item, dict) or "title" not in item:
            continue

        title = unescape(_cdata(item.get("title", ""))).strip()
        article_url = _cdata(item.get("url", "")).strip()
        descr = unescape(_cdata(item.get("descr", ""))).strip()
        content = unescape(_cdata(item.get("content_1000", ""))).strip()
        date_str = _cdata(item.get("lnchdt", "")).strip()

        if not title or not article_url:
            continue

        # 過濾非英文內容（API 無穩定的 lang_exact 參數）
        lang = _cdata(item.get("lang", "")).strip().lower()
        if lang and lang not in ("english", "en", ""):
            continue
        # 備用：檢查 URL 是否指向英文頁面
        if not lang and "/en/" not in article_url and "worldbank.org/en" not in article_url:
            continue

        # Ensure HTTPS
        if article_url.startswith("http://"):
            article_url = "https://" + article_url[7:]

        # Parse date (ISO format: 2026-04-10T15:52:00Z)
        pub_dt = None
        if date_str:
            try:
                pub_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

        if pub_dt and pub_dt < cutoff:
            continue

        articles.append({
            "title": title,
            "content": descr or content,
            "source": "World Bank",
            "source_url": article_url,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": "official",
        })

    logger.info(f"World Bank: fetched {len(articles)} articles from {len(documents)} items")
    return articles
