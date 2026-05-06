"""財新 Caixin Global HTML 爬蟲。

財新 RSS feed 已封鎖（403），改用 HTML 爬蟲抓取 /news/ 頁面：
  GET https://www.caixinglobal.com/news/

文章連結格式：<a href="https://www.caixinglobal.com/YYYY-MM-DD/...html">
頁面約包含 25 則最新文章。
"""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_NEWS_URL = "https://www.caixinglobal.com/news/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html",
}

# Article URL pattern: /YYYY-MM-DD/...
_DATE_PATTERN = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/")


def is_caixin_url(url: str) -> bool:
    """Check whether a URL is a Caixin Global source."""
    return "caixinglobal.com" in url


async def fetch_caixin_news(hours_back: int = 48) -> list[dict]:
    """抓取財新 Caixin Global 最新新聞。

    回傳格式與其他新聞來源相同，可直接接入雷達掃描流程。
    """
    cutoff = datetime.now() - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
            resp = await client.get(_NEWS_URL, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
        mark_attempt(_NEWS_URL, success=True)
    except Exception as e:
        logger.error(f"Caixin fetch error: {e}")
        mark_attempt(_NEWS_URL, success=False, error=str(e))
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 找所有含日期格式的文章連結
    article_links = soup.find_all("a", href=_DATE_PATTERN)
    articles = []
    seen_urls: set[str] = set()

    for link in article_links:
        href = link.get("href", "")
        title = link.get_text(strip=True)

        if not title or len(title) < 10:
            continue

        # Build full URL
        if href.startswith("/"):
            article_url = f"https://www.caixinglobal.com{href}"
        elif href.startswith("http"):
            article_url = href
        else:
            article_url = urljoin(_NEWS_URL, href)

        if article_url in seen_urls:
            continue
        seen_urls.add(article_url)

        # 從 URL 解析日期
        m = _DATE_PATTERN.search(href)
        pub_dt = None
        if m:
            try:
                pub_dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass

        if pub_dt and pub_dt < cutoff:
            continue

        articles.append({
            "title": title,
            "content": title,  # 列表頁無內文摘要
            "source": "財新 Caixin Global",
            "source_url": article_url,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": "financial",
        })

    logger.info(f"Caixin: fetched {len(articles)} articles from {len(article_links)} links")
    return articles
