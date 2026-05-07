"""商業周刊 (businessweekly.com.tw) 「今日最新」HTML 爬蟲。

商周提供 cmsapi RSS feed 但內容偏向 /focus/、/style/，會跳過 /business/ 和雜誌主刊文章。
網站「今日最新」頁面 (https://www.businessweekly.com.tw/latest) 的列表才完整。

該頁面使用 jQuery AJAX 動態載入；後端透過 POST /latest/SearchList 取得 HTML
片段，每頁 20 篇。本爬蟲呼叫此端點並解析 figure.Article-figure 區塊。
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://www.businessweekly.com.tw"
_LIST_API = f"{_BASE}/latest/SearchList"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_BASE}/latest",
}
_TW_TZ = timezone(timedelta(hours=8))
_MAX_PAGES = 3  # 每頁 20 篇，最多抓 60 篇
_FIGURE_RE = re.compile(
    r'<figure[^>]*class="[^"]*Article-figure[^"]*"[^>]*>(.*?)</figure>',
    re.DOTALL,
)


def is_businessweekly_url(url: str) -> bool:
    return "businessweekly.com.tw/latest" in url


def _normalize_url(href: str) -> str:
    href = href.strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return _BASE + href
    return href


def _parse_figure(block: str) -> dict | None:
    # 標題：<div class="Article-content"><a>...</a></div> 內最後一個 <a>
    content_m = re.search(
        r'class="Article-content[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL
    )
    if not content_m:
        return None
    a_m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', content_m.group(1))
    if not a_m:
        return None
    url = _normalize_url(a_m.group(1))
    title = a_m.group(2).strip()
    title = title.replace("&amp;", "&").replace("&quot;", '"')
    if not title or not url:
        return None

    date_m = re.search(r'class="Article-date[^"]*"[^>]*>([^<]+)<', block)
    published_at = None
    if date_m:
        try:
            d = datetime.strptime(date_m.group(1).strip(), "%Y.%m.%d")
            # 商周列表只給日期，當作當地 00:00 → 轉 UTC
            d = d.replace(tzinfo=_TW_TZ).astimezone(timezone.utc)
            published_at = d.replace(tzinfo=None).isoformat()
        except Exception:
            pass

    author_m = re.search(r'class="Article-author[^"]*"[^>]*>([^<]+)<', block)
    author = author_m.group(1).strip() if author_m else ""

    img_m = re.search(r'<img[^>]+alt="([^"]+)"', block)
    summary = img_m.group(1).strip() if img_m else title

    return {
        "title": title,
        "source": "商周",
        "source_url": url,
        "content": (f"{author}　{summary}" if author else summary).strip(),
        "published_at": published_at,
        "category": "radar",
    }


async def fetch_businessweekly_news(hours_back: int = 24) -> list[dict]:
    """抓取商周「今日最新」清單。

    商周列表的日期欄位只有 YYYY.MM.DD，無時間，所以 hours_back 過濾較粗：
    過濾條件改為「文章日期 >= cutoff 日期」（以 UTC 日期判定）。
    """
    from backend.services.source_health import mark_attempt

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_date = cutoff.date()

    articles: list[dict] = []
    seen_urls: set[str] = set()
    last_error: str | None = None

    try:
        async with httpx.AsyncClient(
            timeout=15, headers=_HEADERS, verify=False, follow_redirects=True
        ) as client:
            for page in range(_MAX_PAGES):
                cur = page * 20
                try:
                    resp = await client.post(_LIST_API, data={"CurPage": str(cur)})
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    last_error = str(e)
                    break

                content_html = data.get("Content", "") or ""
                blocks = _FIGURE_RE.findall(content_html)
                if not blocks:
                    break

                page_added = 0
                stop = False
                for blk in blocks:
                    art = _parse_figure(blk)
                    if not art:
                        continue
                    if art["source_url"] in seen_urls:
                        continue
                    # 日期過濾
                    if art.get("published_at"):
                        try:
                            d = datetime.fromisoformat(art["published_at"]).date()
                            if d < cutoff_date:
                                stop = True
                                continue
                        except Exception:
                            pass
                    seen_urls.add(art["source_url"])
                    articles.append(art)
                    page_added += 1

                if data.get("IsLast", "N") == "Y" or stop or page_added == 0:
                    break

        mark_attempt(_BASE + "/latest", success=True)
    except Exception as e:
        last_error = str(e)
        mark_attempt(_BASE + "/latest", success=False, error=last_error)
        logger.warning(f"businessweekly fetch error: {last_error}")
        return []

    logger.info(f"businessweekly: {len(articles)} articles within {hours_back}h")
    return articles
