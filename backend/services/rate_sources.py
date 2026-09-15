"""各國公債殖利率官方資料來源（Yahoo 沒有非美國公債殖利率，只能直接接官方）。

實測結論（2026-09）：
  - Yahoo/yfinance 只有美國：^IRX(3M) / ^FVX(5Y) / ^TNX(10Y) / ^TYX(30Y)，
    另 `2YY=F`（CBOT 2 年期殖利率期貨）可補 2Y。`^JGB10` / `^GDBR10` / `^GB10Y`
    這類國際代碼全部 404。
  - stooq 的多國殖利率 CSV 整站上了 JS proof-of-work 挑戰，不能用。
  - 以下三個官方來源免金鑰、日頻、可直接抓：
      mof_jp     : 日本財務省，1Y~40Y 全年期，歷史檔 + 當月檔兩支合併
      bundesbank : 德國央行 BBSIS，德國公債（Bund）殖利率曲線
      ecb        : 歐洲央行 Data Portal，歐元區 AAA 公債殖利率曲線
      boe        : 英國央行 IADB，單一 series code

新鮮度實測（2026-09-15 週二量測，值為最新資料日）：
      mof_jp     09-14(一) → T-1   ✓
      bundesbank 09-14(一) → T-1   ✓
      ecb        09-11(五) → T-3（落後 2 個交易日）
      boe        09-10(四) → T-5（落後 3 個交易日；IUDMNZC/IUDSNPY/IUDLNPY 三支都一樣，
                                   是來源本身就慢，換 series code 沒用）
德國公債是歐元區的利率基準，且比 ECB 的歐元區 AAA 聚合快兩個交易日，
所以歐洲優先看 bundesbank；ECB 那組保留為歐元區整體參考。

未接：台灣（TPEx 新站是 SPA，OpenAPI 沒有公債殖利率曲線）、韓國（BOK ECOS 需金鑰）。
要新增來源只需寫一個 `_fetch_xxx()` 並在 `_PROVIDERS` 註冊，對外介面不變。
"""

from __future__ import annotations

import csv
import io
import logging
import time
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,*/*",
}

# --- 來源網址 ---
_MOF_HISTORY_URL = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
)
_MOF_CURRENT_URL = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
)
_ECB_URL = (
    "https://data-api.ecb.europa.eu/service/data/YC/"
    "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_{tenor}?format=csvdata&lastNObservations={n}"
)
# tenor 代碼：R02XX=2年、R05XX=5年、R10XX=10年、R30XX=30年
_BBK_URL = (
    "https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
    "D.I.ZST.ZI.EUR.S1311.B.A604.R{tenor}XX.R.A.A._Z._Z.A?format=csv&lang=en"
)
_BBK_TENORS = {"2Y": "02", "5Y": "05", "10Y": "10", "30Y": "30"}

_BOE_URL = (
    "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
    "?csv.x=yes&Datefrom={dfrom}&Dateto={dto}&SeriesCodes={code}"
    "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
)

# 來源網頁（給前端「資料來源」連結用）
SOURCE_PAGES = {
    "mof_jp": ("日本財務省", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"),
    "bundesbank": ("德國央行 (Bundesbank)",
                   "https://www.bundesbank.de/en/statistics/money-and-capital-markets/interest-rates-and-yields"),
    "ecb": ("歐洲央行 (ECB)", "https://data.ecb.europa.eu/data/datasets/YC"),
    "boe": ("英國央行 (BoE)", "https://www.bankofengland.co.uk/boeapps/database/"),
}

# --- 記憶體快取：{cache_key: (expires_at, payload)} ---
_cache: dict[str, tuple[float, object]] = {}
# 歷史檔一個月才更新一次，當月檔一天更新一次
_TTL_HISTORY = 12 * 3600
_TTL_DAILY = 3600


def _cache_get(key: str):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_put(key: str, value, ttl: float):
    _cache[key] = (time.time() + ttl, value)


async def _get_text(client: httpx.AsyncClient, url: str) -> str | None:
    """抓文字內容；有些站台會用 HTTP 200 回 HTML 404 頁，這裡一併擋掉。"""
    try:
        r = await client.get(url, timeout=40, headers=_HEADERS, follow_redirects=True)
        r.raise_for_status()
        body = r.text
        head = body[:300].lstrip().lower()
        if head.startswith("<!doctype") or "<html" in head:
            logger.warning(f"rate_sources: {url} 回了 HTML（多半是 404 頁）")
            return None
        return body
    except Exception as e:
        logger.warning(f"rate_sources: 抓取 {url} 失敗: {e}")
        return None


def _series(rows: list[tuple[datetime, float]]) -> list[dict]:
    """統一輸出格式，與 market_data.get_market_history 對齊（時間升序）。"""
    rows.sort(key=lambda r: r[0])
    return [{"time": d.isoformat(), "close": round(v, 4)} for d, v in rows]


# ---------------------------------------------------------------- 日本 MOF

def _parse_mof_csv(text: str, tenor: str) -> list[tuple[datetime, float]]:
    """MOF CSV 格式：第 2 行是表頭 Date,1Y,2Y,...,40Y；日期為 YYYY/M/D。

    未開市的日子該欄是 '-'，直接略過。
    """
    out: list[tuple[datetime, float]] = []
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    for row in reader:
        if not row or not row[0].strip():
            continue
        if header is None:
            if row[0].strip().lower() == "date":
                header = [c.strip() for c in row]
            continue
        try:
            idx = header.index(tenor)
        except ValueError:
            return []
        if idx >= len(row):
            continue
        raw = row[idx].strip()
        if not raw or raw == "-":
            continue
        try:
            out.append((datetime.strptime(row[0].strip(), "%Y/%m/%d"), float(raw)))
        except ValueError:
            continue
    return out


async def _fetch_mof_jp(client: httpx.AsyncClient, tenor: str, days: int) -> list[dict]:
    """日本財務省 JGB 殖利率。歷史檔只到上月底，必須再併當月檔才有最新幾天。"""
    hist = _cache_get("mof:history")
    if hist is None:
        hist = await _get_text(client, _MOF_HISTORY_URL) or ""
        _cache_put("mof:history", hist, _TTL_HISTORY)

    cur = _cache_get("mof:current")
    if cur is None:
        cur = await _get_text(client, _MOF_CURRENT_URL) or ""
        _cache_put("mof:current", cur, _TTL_DAILY)

    merged: dict[datetime, float] = {}
    for text in (hist, cur):
        if text:
            for d, v in _parse_mof_csv(text, tenor):
                merged[d] = v
    if not merged:
        return []
    cutoff = datetime.utcnow() - timedelta(days=days)
    return _series([(d, v) for d, v in merged.items() if d >= cutoff])


# ---------------------------------------------------------------- 德國央行

async def _fetch_bundesbank(client: httpx.AsyncClient, tenor: str, days: int) -> list[dict]:
    """德國公債殖利率（Svensson 法擬合的利率期限結構）。

    CSV 前幾行是標題與說明，資料列格式 `YYYY-MM-DD,值,旗標`；非交易日的值是 "."。
    """
    code = _BBK_TENORS.get(tenor)
    if not code:
        return []
    cache_key = f"bbk:{code}"
    text = _cache_get(cache_key)
    if text is None:
        text = await _get_text(client, _BBK_URL.format(tenor=code)) or ""
        _cache_put(cache_key, text, _TTL_DAILY)
    if not text:
        return []

    out: list[tuple[datetime, float]] = []
    for line in text.split("\n"):
        parts = line.split(",")
        if len(parts) < 2:
            continue
        raw_date = parts[0].strip().strip('"')
        raw_val = parts[1].strip().strip('"')
        if len(raw_date) != 10 or raw_date[4] != "-":
            continue
        if not raw_val or raw_val == ".":
            continue          # 非交易日
        try:
            out.append((datetime.strptime(raw_date, "%Y-%m-%d"), float(raw_val)))
        except ValueError:
            continue
    cutoff = datetime.utcnow() - timedelta(days=days)
    return _series([(d, v) for d, v in out if d >= cutoff])


# ---------------------------------------------------------------- ECB

async def _fetch_ecb(client: httpx.AsyncClient, tenor: str, days: int) -> list[dict]:
    """歐元區 AAA 公債殖利率曲線。tenor 例：'2Y' / '10Y' / '30Y'。"""
    n = max(days + 30, 60)          # 多要一些，扣掉週末假日才夠
    url = _ECB_URL.format(tenor=tenor, n=min(n, 1000))
    text = await _get_text(client, url)
    if not text:
        return []
    out: list[tuple[datetime, float]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        raw_date = (row.get("TIME_PERIOD") or "").strip()
        raw_val = (row.get("OBS_VALUE") or "").strip()
        if not raw_date or not raw_val:
            continue
        try:
            out.append((datetime.strptime(raw_date, "%Y-%m-%d"), float(raw_val)))
        except ValueError:
            continue
    cutoff = datetime.utcnow() - timedelta(days=days)
    return _series([(d, v) for d, v in out if d >= cutoff])


# ---------------------------------------------------------------- BoE

async def _fetch_boe(client: httpx.AsyncClient, code: str, days: int) -> list[dict]:
    """英國央行 IADB。code 為 series code（10Y 名目殖利率＝IUDMNZC）。"""
    dto = datetime.utcnow()
    dfrom = dto - timedelta(days=days + 10)
    url = _BOE_URL.format(
        dfrom=dfrom.strftime("%d/%b/%Y"), dto=dto.strftime("%d/%b/%Y"), code=code
    )
    text = await _get_text(client, url)
    if not text:
        return []
    out: list[tuple[datetime, float]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        raw_date = (row.get("DATE") or "").strip()
        raw_val = (row.get(code) or "").strip()
        if not raw_date or not raw_val:
            continue
        try:
            out.append((datetime.strptime(raw_date, "%d %b %Y"), float(raw_val)))
        except ValueError:
            continue
    return _series(out)


_PROVIDERS = {
    "mof_jp": _fetch_mof_jp,
    "bundesbank": _fetch_bundesbank,
    "ecb": _fetch_ecb,
    "boe": _fetch_boe,
}


def is_supported(provider: str | None) -> bool:
    return bool(provider) and provider in _PROVIDERS


async def fetch_series(provider: str, provider_symbol: str, days: int = 400) -> list[dict]:
    """取得某官方來源的日頻序列，格式同 market_data.get_market_history。

    失敗一律回空 list（呼叫端當成「這輪沒資料」處理，不讓單一來源掛掉整個看板）。
    """
    fn = _PROVIDERS.get(provider)
    if not fn:
        return []
    key = f"{provider}:{provider_symbol}:{days}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(verify=False) as client:
        try:
            data = await fn(client, provider_symbol, days)
        except Exception as e:
            logger.error(f"rate_sources.fetch_series({provider}, {provider_symbol}) 失敗: {e}")
            data = []
    if data:
        _cache_put(key, data, _TTL_DAILY)
    return data


async def fetch_many(specs: list[tuple[str, str]], days: int = 400) -> dict[tuple[str, str], list[dict]]:
    """批次取得多組 (provider, provider_symbol)。

    同來源的多個年期共用 HTTP 快取（例如日本 1Y/2Y/10Y/30Y 只會抓兩支 CSV）。
    """
    import asyncio

    results = await asyncio.gather(
        *[fetch_series(p, s, days) for p, s in specs], return_exceptions=True
    )
    out: dict[tuple[str, str], list[dict]] = {}
    for spec, res in zip(specs, results):
        out[spec] = res if isinstance(res, list) else []
    return out
