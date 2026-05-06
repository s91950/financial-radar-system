"""金管會 (FSC) 新聞稿 HTML 爬蟲。

金管會 RSS feed 已失效（回傳 HTML 而非 XML），改用 HTML 爬蟲抓取新聞列表：
  GET https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2&mcustomize=news_list.jsp

列表頁包含約 15 則新聞連結，以 <a href="...news_view.jsp..."> 格式呈現。
每則新聞有標題文字及發布日期（從 URL 參數或頁面文字擷取）。
"""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_NEWS_LIST_URL = "https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2&mcustomize=news_list.jsp"
_BASE_URL = "https://www.fsc.gov.tw/ch/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html",
}


def is_fsc_url(url: str) -> bool:
    """Check whether a URL is an FSC news source."""
    return "fsc.gov.tw" in url and ("news_list" in url or "rss" in url)


def _parse_date_from_text(text: str) -> datetime | None:
    """嘗試從日期文字解析民國年或西元年日期。

    支援格式：
      - 115-04-10 / 115.04.10 / 115/04/10 (民國年)
      - 2026-04-10 / 2026.04.10 / 2026/04/10 (西元年)
    """
    m = re.search(r"(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 200:  # 民國年
            y += 1911
        return datetime(y, mo, d)
    except Exception:
        return None


async def fetch_fsc_news(hours_back: int = 48) -> list[dict]:
    """抓取金管會新聞稿列表。

    回傳格式與其他新聞來源相同，可直接接入雷達掃描流程。
    """
    cutoff = datetime.now() - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
            resp = await client.get(_NEWS_LIST_URL, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
        mark_attempt(_NEWS_LIST_URL, success=True)
    except Exception as e:
        logger.error(f"FSC fetch error: {e}")
        mark_attempt(_NEWS_LIST_URL, success=False, error=str(e))
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 新聞連結格式：<a href="home.jsp?...news_view.jsp...">標題</a>
    # 或含完整 URL 如 https://www.sfb.gov.tw/...
    links = soup.find_all("a", href=re.compile(r"news_view\.jsp|news_view"))
    articles = []
    seen_urls: set[str] = set()

    for link in links:
        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        href = link.get("href", "")
        if not href:
            continue

        # Build full URL
        if href.startswith("http"):
            article_url = href
        else:
            article_url = urljoin(_BASE_URL, href)

        if article_url in seen_urls:
            continue
        seen_urls.add(article_url)

        # 嘗試從 URL 參數或周圍文字解析日期
        pub_dt = _parse_date_from_text(href)
        if not pub_dt:
            # 嘗試從連結的父元素找日期
            parent = link.parent
            if parent:
                parent_text = parent.get_text()
                pub_dt = _parse_date_from_text(parent_text)

        if pub_dt and pub_dt < cutoff:
            continue

        articles.append({
            "title": title,
            "content": title,  # 列表頁無內文摘要
            "source": "金管會",
            "source_url": article_url,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": "official",
        })

    logger.info(f"FSC: fetched {len(articles)} articles from {len(links)} links")
    return articles
