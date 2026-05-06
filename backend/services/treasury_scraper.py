"""US Treasury 美國財政部新聞稿爬蟲。

home.treasury.gov 的 /rss.xml feed 主要是行政頁面更新（不是新聞稿），
真正的財政部新聞稿在 /news/press-releases，server-side rendered HTML，
每筆包在 <div class="mm-news-row"> 內，含 <time datetime="..."> 與
<a href="/news/press-releases/sbXXXX"> 的標題連結。

每頁 ~16 篇，涵蓋約 1-2 週，足以做 24h-48h 雷達掃描。
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_LIST_URL = "https://home.treasury.gov/news/press-releases"
_BASE = "https://home.treasury.gov"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def is_treasury_url(url: str) -> bool:
    """匹配 home.treasury.gov 新聞稿頁面或 RSS。"""
    return "home.treasury.gov" in url and ("press-releases" in url or "rss" in url)


async def fetch_treasury_news(hours_back: int = 48) -> list[dict]:
    """抓取 US Treasury 最新新聞稿。

    回傳格式與其他爬蟲一致，可直接接入雷達掃描流程。
    """
    from backend.services.source_health import mark_attempt
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    try:
        async with httpx.AsyncClient(
            timeout=20, verify=False, follow_redirects=True
        ) as client:
            resp = await client.get(_LIST_URL, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
        mark_attempt(_LIST_URL, success=True)
    except Exception as e:
        logger.warning(f"US Treasury fetch error: {e}")
        mark_attempt(_LIST_URL, success=False, error=str(e))
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("div", class_="mm-news-row")
    articles: list[dict] = []
    seen: set[str] = set()

    for row in rows:
        time_tag = row.find("time")
        link_tag = row.select_one(".news-title a, a[href*='/news/press-releases/']")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        if not href:
            continue
        article_url = urljoin(_BASE, href)
        if article_url in seen:
            continue

        title = link_tag.get_text(strip=True).replace("​", "")  # strip zero-width space
        if not title or len(title) < 5:
            continue

        pub_dt = None
        if time_tag and time_tag.get("datetime"):
            dt_str = time_tag["datetime"]
            try:
                pub_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except ValueError:
                # 容錯：例如 "May 4, 2026" 形式（rare fallback）
                try:
                    pub_dt = datetime.strptime(dt_str.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pub_dt = None

        # 沒有日期的列：保留（通常是 featured 最新項，HTML 內含日期但格式變動）
        # 有日期但超過 cutoff：略過
        if pub_dt and pub_dt < cutoff:
            continue

        seen.add(article_url)
        articles.append({
            "title": title,
            "content": "",
            "source": "US Treasury",
            "source_url": article_url,
            "published_at": pub_dt.astimezone(timezone.utc).isoformat() if pub_dt else None,
            "category": "official",
        })

    logger.info(f"US Treasury: {len(articles)} press releases within {hours_back}h")
    return articles
