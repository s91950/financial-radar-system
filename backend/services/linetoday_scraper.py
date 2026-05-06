"""LINE Today 今日新聞 scraper.

LINE Today 沒有公開 RSS feed，但首頁以 Next.js SSR 方式在 HTML 中嵌入
__NEXT_DATA__ JSON，包含完整文章清單（標題、時間、描述）。
解析該 JSON 取出國際新聞文章。
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

LINETODAY_URL = "https://today.line.me/tw/v3/tab/global"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def is_linetoday_url(url: str) -> bool:
    return "today.line.me" in url


async def fetch_linetoday_news(hours_back: int = 24) -> list[dict]:
    """解析 LINE Today 國際版頁面，回傳指定時間內的文章清單。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
            r = await client.get(LINETODAY_URL)
            r.raise_for_status()
            html = r.text
        mark_attempt(LINETODAY_URL, success=True)
    except Exception as e:
        logger.warning(f"linetoday fetch error: {e}")
        mark_attempt(LINETODAY_URL, success=False, error=str(e))
        return []

    # 從 HTML 中取出 __NEXT_DATA__ JSON
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html, re.DOTALL)
    if not m:
        logger.warning("linetoday: __NEXT_DATA__ not found in page")
        return []

    try:
        next_data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"linetoday: JSON parse error: {e}")
        return []

    # 遞迴搜尋所有 article 物件（含 title + publishTimeUnix + id）
    articles: list[dict] = []
    seen_ids: set[str] = set()

    def _walk(obj):
        if isinstance(obj, dict):
            # 辨識文章節點：必須有 title、id、publishTimeUnix
            if "title" in obj and "id" in obj and "publishTimeUnix" in obj:
                article_id = str(obj.get("id", ""))
                if article_id and article_id not in seen_ids:
                    seen_ids.add(article_id)
                    _process_article(obj)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    def _process_article(obj):
        try:
            ts_ms = int(obj["publishTimeUnix"])
            pub_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        except (KeyError, ValueError, OSError):
            return

        if pub_dt < cutoff:
            return

        title = obj.get("title", "").strip()
        if not title or len(title) < 5:
            return

        article_id = str(obj.get("id", ""))
        url = f"https://today.line.me/tw/v3/article/{article_id}"

        publisher = ""
        pub_info = obj.get("publisher") or obj.get("publisherName") or ""
        if isinstance(pub_info, dict):
            publisher = pub_info.get("name", "")
        elif isinstance(pub_info, str):
            publisher = pub_info

        desc = obj.get("shortDescription") or obj.get("description") or ""
        if isinstance(desc, str):
            desc = desc.strip()

        articles.append({
            "title": title,
            "source": "LINE Today 國際",
            "source_url": url,
            "content": desc,
            "published_at": pub_dt.isoformat(),
            "category": "radar",
        })

    _walk(next_data)

    logger.info(f"linetoday: {len(articles)} articles within {hours_back}h")
    return articles
