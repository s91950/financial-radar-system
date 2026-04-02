"""公開資訊觀測站 (MOPS) 重大訊息爬蟲。

使用 MOPS AJAX API 抓取上市/上櫃公司重大訊息，回傳格式與其他新聞來源相同。
每次最多各抓 100 筆，合併上市 (sii) + 上櫃 (otc) 結果後去重。
"""

import logging
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MOPS_URL = "https://mops.twse.com.tw/mops/web/ajax_t05sr01"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://mops.twse.com.tw/mops/web/t05sr01",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _roc_year(dt: datetime) -> str:
    """西元年 → 民國年（字串）。"""
    return str(dt.year - 1911)


async def _fetch_typek(client: httpx.AsyncClient, typek: str, b_date: str, e_date: str) -> list[dict]:
    """抓取單一市場類型（sii=上市 / otc=上櫃）的重大訊息。"""
    now = datetime.now()
    form = {
        "encodeURIComponent": "1",
        "step": "0",
        "firstin": "1",
        "off": "1",
        "TYPEK": typek,
        "TYPEK2": "",
        "year": _roc_year(now),
        "month": str(now.month).zfill(2),
        "b_date": b_date,
        "e_date": e_date,
        "query_date": "",
        "co_id": "",
        "keyword4": "",
        "code1": "",
        "isnew": "false",
    }
    try:
        resp = await client.post(_MOPS_URL, data=form, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"MOPS fetch ({typek}) failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    # MOPS 回傳的 HTML 中，重大訊息在 table.hasBorder 或 class=result_table
    table = soup.find("table", class_=lambda c: c and ("hasBorder" in c or "result" in c.lower()))
    if not table:
        # fallback: any <table> with many rows
        tables = soup.find_all("table")
        table = max(tables, key=lambda t: len(t.find_all("tr")), default=None) if tables else None
    if not table:
        return []

    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header
        cols = row.find_all("td")
        if len(cols) < 5:
            continue
        try:
            # 欄位順序：公司代號 / 公司名稱 / 發言日期 / 發言時間 / 主旨 / 說明
            stock_id   = cols[0].get_text(strip=True)
            stock_name = cols[1].get_text(strip=True)
            date_str   = cols[2].get_text(strip=True)   # 民國年 e.g. "113/04/01"
            time_str   = cols[3].get_text(strip=True)   # e.g. "08:30:00"
            subject    = cols[4].get_text(strip=True)
            detail     = cols[5].get_text(strip=True) if len(cols) > 5 else ""

            # 解析民國日期 → datetime
            pub_dt = None
            try:
                parts = date_str.replace("年", "/").replace("月", "/").replace("日", "").split("/")
                if len(parts) == 3:
                    y = int(parts[0]) + 1911  # 民國 → 西元
                    m, d = int(parts[1]), int(parts[2])
                    t_parts = time_str.split(":")
                    h = int(t_parts[0]) if t_parts else 0
                    mi = int(t_parts[1]) if len(t_parts) > 1 else 0
                    pub_dt = datetime(y, m, d, h, mi)
            except Exception:
                pass

            # 組合標題：公司名稱 + 主旨
            title = f"【{stock_id} {stock_name}】{subject}"
            content = detail[:500] if detail else subject

            # 組合連結：MOPS 查詢頁（帶公司代號）
            source_url = (
                f"https://mops.twse.com.tw/mops/web/t05sr01"
                f"?TYPEK={typek}&co_id={stock_id}"
            )

            articles.append({
                "title": title,
                "content": content,
                "source": "公開資訊觀測站",
                "source_url": source_url,
                "published_at": pub_dt.isoformat() if pub_dt else None,
                "category": "mops",
            })
        except Exception:
            continue

    return articles


async def fetch_mops_material_news(hours_back: int = 24) -> list[dict]:
    """抓取 MOPS 上市 + 上櫃 重大訊息。

    回傳格式與 rss_feed / google_news 相同，可直接接入雷達掃描流程。
    """
    now = datetime.now()
    start = now - timedelta(hours=hours_back)
    b_date = start.strftime("%Y%m%d")
    e_date = now.strftime("%Y%m%d")

    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        sii_articles, otc_articles = await __import__("asyncio").gather(
            _fetch_typek(client, "sii", b_date, e_date),
            _fetch_typek(client, "otc", b_date, e_date),
        )

    all_articles = sii_articles + otc_articles

    # 去重（同公司 + 同主旨）
    seen: set[str] = set()
    unique: list[dict] = []
    for a in all_articles:
        key = a["source_url"] + a["title"]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    logger.info(f"MOPS: 抓到 {len(unique)} 則重大訊息 (sii={len(sii_articles)}, otc={len(otc_articles)})")
    return unique
