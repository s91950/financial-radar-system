"""公開資訊觀測站 (MOPS) 重大訊息爬蟲。

使用 MOPS Vue SPA 後端 JSON API 抓取上市/上櫃公司重大訊息，回傳格式與其他新聞來源相同。
每次最多各抓 100 筆，合併上市 (sii) + 上櫃 (otc) 結果後去重。

MOPS 於 2025 年底全面改版為 Vue SPA，舊版 AJAX HTML endpoint
(mops/web/ajax_t05sr01) 已被安全政策封鎖，改用新版 JSON API：
  POST https://mops.twse.com.tw/mops/api/home_page/t05sr01_1
  Content-Type: application/json
  Body: {"count": N, "marketKind": "sii"|"otc"}
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://mops.twse.com.tw/mops/api/home_page/t05sr01_1"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://mops.twse.com.tw",
    "Referer": "https://mops.twse.com.tw/",
}


def _parse_roc_datetime(date_str: str, time_str: str) -> datetime | None:
    """解析民國年日期 + 時間字串。

    date_str: "115/04/11"
    time_str: "10:50"
    """
    m = re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", date_str.strip())
    if not m:
        return None
    try:
        roc_y, mo, day = (int(x) for x in m.groups())
        hh, mm = 0, 0
        tm = re.match(r"(\d{1,2}):(\d{1,2})", time_str.strip())
        if tm:
            hh, mm = int(tm.group(1)), int(tm.group(2))
        return datetime(roc_y + 1911, mo, day, hh, mm)
    except Exception:
        return None


def _parse_item(item: dict, market_kind: str) -> dict | None:
    """解析單筆 JSON API 回傳的重大訊息。"""
    company_id = (item.get("companyId") or "").strip()
    company_name = (item.get("companyAbbreviation") or "").strip()
    subject = (item.get("subject") or "").replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()

    if not company_id or not subject:
        return None

    date_str = item.get("date", "")
    time_str = item.get("time", "")
    pub_dt = _parse_roc_datetime(date_str, time_str)

    title = f"【{company_id} {company_name}】{subject}"
    source_url = (
        f"https://mops.twse.com.tw/mops/#/web/t05sr01_1"
        f"?TYPEK={market_kind}&co_id={company_id}"
    )
    return {
        "title": title,
        "content": subject,
        "source": "公開資訊觀測站",
        "source_url": source_url,
        "published_at": pub_dt.isoformat() if pub_dt else None,
        "category": "mops",
        "_pub_dt": pub_dt,  # 供日期過濾用，不存入 DB
    }


async def _fetch_market(
    client: httpx.AsyncClient, market_kind: str, count: int = 100
) -> list[dict]:
    """抓取單一市場類型（sii=上市 / otc=上櫃）的重大訊息。"""
    try:
        resp = await client.post(
            _API_URL,
            headers=_HEADERS,
            json={"count": count, "marketKind": market_kind},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"MOPS fetch ({market_kind}) failed: {e}")
        return []

    items = data.get("result", {}).get("data", [])
    articles = []
    for raw_item in items:
        try:
            parsed = _parse_item(raw_item, market_kind)
            if parsed:
                articles.append(parsed)
        except Exception as exc:
            logger.debug(f"MOPS item parse error: {exc}")
            continue

    logger.debug(f"MOPS ({market_kind}): parsed {len(articles)} articles from {len(items)} items")
    return articles


async def fetch_mops_material_news(hours_back: int = 24) -> list[dict]:
    """抓取 MOPS 上市 + 上櫃 重大訊息。

    回傳格式與 rss_feed / google_news 相同，可直接接入雷達掃描流程。
    """
    cutoff = datetime.now() - timedelta(hours=hours_back)

    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        sii_articles, otc_articles = await asyncio.gather(
            _fetch_market(client, "sii"),
            _fetch_market(client, "otc"),
        )

    all_articles = sii_articles + otc_articles

    # 以 published_at 做時間過濾；pub_dt=None 的一律保留（時間不詳但今日抓到）
    filtered = []
    for a in all_articles:
        pub_dt = a.pop("_pub_dt", None)  # 移除暫存欄位
        if pub_dt is None or pub_dt >= cutoff:
            filtered.append(a)

    # 去重（同 source_url + 標題）
    seen: set[str] = set()
    unique: list[dict] = []
    for a in filtered:
        key = a["source_url"] + a["title"]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    logger.info(
        f"MOPS: 抓到 {len(unique)} 則重大訊息 "
        f"(sii={len(sii_articles)}, otc={len(otc_articles)}, after_filter={len(filtered)})"
    )
    return unique
