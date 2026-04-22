"""UDN 聯合新聞網分類頁爬蟲。

udn.com 的分類頁（如 /news/cate/2/6644）是 server-side rendered HTML，
直接解析取得文章連結、標題、發布時間，無需 RSS feed 或 JS 執行。
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://udn.com/",
}
_BASE = "https://udn.com"


def is_udn_cate_url(url: str) -> bool:
    """僅匹配 udn.com/news/cate/ 分類頁，不攔截 money.udn.com 或 RSS URL。"""
    return "udn.com/news/cate/" in url


async def fetch_udn_cate_news(url: str, hours_back: int = 24) -> list[dict]:
    """解析 UDN 分類頁，回傳指定時間內的文章清單。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    tw_offset = timezone(timedelta(hours=8))  # 頁面時間為台灣時間

    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        logger.warning(f"udn cate fetch error ({url}): {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    articles: list[dict] = []
    seen: set[str] = set()

    # 找所有 /news/story/... 文章連結
    for a_tag in soup.find_all("a", href=re.compile(r"/news/story/\d+/\d+")):
        href = a_tag.get("href", "")
        article_url = href if href.startswith("http") else _BASE + href
        if article_url in seen:
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 5:
            # 可能是包圖片的連結，往上找標題
            parent = a_tag.find_parent(["li", "div", "article"])
            if parent:
                h_tag = parent.find(["h2", "h3", "h4"])
                title = h_tag.get_text(strip=True) if h_tag else ""
        if not title or len(title) < 5:
            continue

        # 在同一父容器找時間標籤（格式：2026-04-22 10:31）
        pub_dt = None
        container = a_tag.find_parent(["li", "div", "article", "section"])
        if container:
            time_tag = container.find("time")
            if time_tag:
                dt_str = time_tag.get("datetime") or time_tag.get_text(strip=True)
                pub_dt = _parse_tw_time(dt_str, tw_offset)
            if not pub_dt:
                # fallback：用 regex 找 YYYY-MM-DD HH:MM 格式
                text = container.get_text(" ")
                m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", text)
                if m:
                    pub_dt = _parse_tw_time(f"{m.group(1)} {m.group(2)}", tw_offset)

        if pub_dt and pub_dt < cutoff:
            continue

        seen.add(article_url)
        articles.append({
            "title": title,
            "source": "聯合新聞網",
            "source_url": article_url,
            "content": "",
            "published_at": pub_dt.isoformat() if pub_dt else "",
            "category": "radar",
        })

    logger.info(f"udn cate: {len(articles)} articles within {hours_back}h from {url}")
    return articles


def _parse_tw_time(dt_str: str, tw_offset: timezone) -> datetime | None:
    """解析台灣時間字串，轉為 UTC aware datetime。"""
    dt_str = dt_str.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(dt_str[:16], fmt)
            return dt.replace(tzinfo=tw_offset).astimezone(timezone.utc)
        except ValueError:
            continue
    return None
