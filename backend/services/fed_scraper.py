"""聯準會 (Fed) recentpostings.htm 爬蟲。

federalreserve.gov/recentpostings.htm 是 Fed 全站最新消息彙整頁，
涵蓋所有類型（新聞稿、演講、FEDS Notes、Beige Book、統計發布、會議通知等），
比任何單一 RSS feed 更完整。頁面為 server-side rendered HTML，無分頁。

解析結構：
  <div class="eventlist__time"><time>4/22/2026</time></div>
  <div class="eventlist__event">
    <p><a href="/newsevents/...">Press Release</a></p>
    <p>Federal Reserve Board issues ...</p>
  </div>
"""

import logging
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_URL = "https://www.federalreserve.gov/recentpostings.htm"
_BASE = "https://www.federalreserve.gov"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def is_fed_url(url: str) -> bool:
    """Check whether a URL is the Fed recentpostings page."""
    return "federalreserve.gov/recentpostings" in url


def _parse_date(date_str: str) -> datetime | None:
    """解析 M/D/YYYY 或 MM/DD/YYYY 格式，回傳 UTC-aware datetime（設為當天 00:00 UTC）。"""
    date_str = date_str.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_str)
    if not m:
        return None
    try:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, 0, 0, 0, tzinfo=timezone.utc)
    except ValueError:
        return None


async def fetch_fed_news(hours_back: int = 48) -> list[dict]:
    """抓取 Fed recentpostings.htm 全站最新消息。

    回傳格式與其他爬蟲一致，可直接接入雷達掃描流程。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(
            timeout=20, verify=False, follow_redirects=True
        ) as client:
            resp = await client.get(_URL, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
        mark_attempt(_URL, success=True)
    except Exception as e:
        logger.error(f"Fed recentpostings fetch error: {e}")
        mark_attempt(_URL, success=False, error=str(e))
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 找所有 eventlist row（每一筆 = 一則消息）
    # 結構：.eventlist__time 和 .eventlist__event 在同一個 .row 下
    articles = []
    seen_urls: set[str] = set()

    event_rows = soup.select("div.row.eventlist div.row, div.eventlist > div.row")
    if not event_rows:
        # fallback：找所有含 eventlist__time 的 row
        event_rows = []
        for time_div in soup.select("div.eventlist__time"):
            row = time_div.parent
            if row:
                event_rows.append(row)

    for row in event_rows:
        # 日期
        time_tag = row.select_one("div.eventlist__time time, time")
        if not time_tag:
            continue
        pub_dt = _parse_date(time_tag.get_text())
        if pub_dt and pub_dt < cutoff:
            continue  # 超過時間範圍

        # 事件類型 + URL
        event_div = row.select_one("div.eventlist__event")
        if not event_div:
            continue

        paras = event_div.find_all("p")
        if not paras:
            continue

        # 第一個 <p> 含連結：文章類型
        type_link = paras[0].find("a") if paras else None
        href = type_link["href"] if type_link and type_link.get("href") else ""
        post_type = type_link.get_text(strip=True) if type_link else ""

        # 第二個 <p>（若有）是描述文字
        desc = ""
        if len(paras) >= 2:
            desc = paras[1].get_text(strip=True)
        elif len(paras) == 1 and not type_link:
            desc = paras[0].get_text(strip=True)

        # 若 desc 為空，用 type 作備用標題
        title = desc if desc else post_type
        if not title or len(title) < 5:
            continue

        # 建立完整 URL
        if href.startswith("http"):
            article_url = href
        elif href:
            article_url = urljoin(_BASE, href)
        else:
            article_url = _URL  # fallback

        if article_url in seen_urls:
            continue
        seen_urls.add(article_url)

        # 內容：合併類型標籤 + 描述，方便關鍵字匹配
        content = f"[{post_type}] {desc}" if post_type and desc else title

        articles.append({
            "title": title,
            "content": content,
            "source": "聯準會 (Fed)",
            "source_url": article_url,
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "category": "official",
        })

    logger.info(f"Fed recentpostings: fetched {len(articles)} articles")
    return articles
