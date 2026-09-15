"""Market data service using Yahoo Finance and TWSE API."""

import asyncio
import logging
import re
from datetime import datetime

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)


def _quotes_sync(symbols: list[str]) -> list[dict]:
    """Blocking yfinance quote fetch — call via asyncio.to_thread."""
    results = []
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for symbol in symbols:
            try:
                ticker = tickers.tickers.get(symbol)
                if not ticker:
                    continue
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)

                change_pct = 0
                if price and prev_close and prev_close != 0:
                    change_pct = ((price - prev_close) / prev_close) * 100

                results.append({
                    "symbol": symbol,
                    "price": round(price, 2) if price else None,
                    "change_percent": round(change_pct, 2),
                    "previous_close": round(prev_close, 2) if prev_close else None,
                    "last_updated": datetime.utcnow().isoformat(),
                })
            except Exception as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")
                results.append({
                    "symbol": symbol,
                    "price": None,
                    "change_percent": 0,
                    "last_updated": None,
                    "error": str(e),
                })
    except Exception as e:
        logger.error(f"yfinance batch error: {e}")

    return results


async def get_market_quotes(symbols: list[str]) -> list[dict]:
    """Fetch current market data for a list of symbols via yfinance."""
    if not symbols:
        return []
    return await asyncio.to_thread(_quotes_sync, symbols)


def get_history_sync(symbol: str, period: str = "5d", interval: str = "1h") -> list[dict]:
    """Blocking history fetch — call via asyncio.to_thread from async contexts."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        return [
            {
                "time": idx.isoformat(),
                "open": round(row["Open"], 4),
                "high": round(row["High"], 4),
                "low": round(row["Low"], 4),
                "close": round(row["Close"], 4),
                "volume": int(row["Volume"]),
            }
            for idx, row in hist.iterrows()
        ]
    except Exception as e:
        logger.error(f"yfinance history error ({symbol}): {e}")
        return []


async def get_market_history(symbol: str, period: str = "5d", interval: str = "1h") -> list[dict]:
    """Fetch historical market data for charting.

    yfinance 是同步阻塞的；丟到 thread 避免卡住 event loop
    （排程器同一個 loop 上還有 radar_scan，阻塞會造成 APScheduler misfire）。
    """
    return await asyncio.to_thread(get_history_sync, symbol, period, interval)


async def get_twse_index() -> dict | None:
    """Fetch Taiwan Stock Exchange weighted index from TWSE API."""
    try:
        url = "https://www.twse.com.tw/exchangeReport/FMTQIK"
        params = {"response": "json", "date": datetime.now().strftime("%Y%m%d")}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("stat") == "OK" and data.get("data"):
            latest = data["data"][-1]
            return {
                "date": latest[0],
                "volume": latest[1],
                "amount": latest[2],
                "open": latest[3],
                "high": latest[4],
                "low": latest[5],
                "close": latest[6],
            }
    except Exception as e:
        logger.error(f"TWSE API error: {e}")
    return None


async def get_twse_realtime() -> dict | None:
    """Fetch TWSE real-time index data."""
    try:
        url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        params = {"ex_ch": "tse_t00.tw", "json": "1", "delay": "0"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("msgArray"):
            item = data["msgArray"][0]
            return {
                "symbol": "^TWII",
                "name": "台股加權指數",
                "price": float(item.get("z", 0)),
                "open": float(item.get("o", 0)),
                "high": float(item.get("h", 0)),
                "low": float(item.get("l", 0)),
                "yesterday_close": float(item.get("y", 0)),
                "volume": item.get("v", "0"),
                "time": item.get("t", ""),
            }
    except Exception as e:
        logger.error(f"TWSE realtime error: {e}")
    return None


# ============================================================================
# Provider 分派層
#
# Yahoo 只有美國公債殖利率；日本／歐元區／英國必須直接接官方來源（見
# services/rate_sources.py）。利差之類的衍生指標則由其他指標的值算出來。
# 對外只暴露 get_quotes_for_items() / get_history_for_item()，呼叫端不必知道
# 某個指標的資料是從哪來的。
# ============================================================================

# 衍生指標算式語法：用大括號包住指標代碼，例 "{^TNX} - {2YY=F}"。
# 不用裸符號是因為 ^TNX / 2YY=F / DX-Y.NYB 本身就含 ^ = - . 這些運算子字元。
_FORMULA_TOKEN = re.compile(r"\{([^{}]+)\}")
# 代換完只允許純算術，擋掉任何函式呼叫或屬性存取
_SAFE_EXPR = re.compile(r"^[0-9+\-*/(). ]+$")


def formula_symbols(formula: str) -> list[str]:
    """取出算式引用到的指標代碼。"""
    return [m.strip() for m in _FORMULA_TOKEN.findall(formula or "") if m.strip()]


def eval_formula(formula: str, values: dict[str, float]) -> float | None:
    """以 *values* 代入算式求值；缺任一成分或算式不合法就回 None。"""
    if not formula:
        return None
    missing = [sym for sym in formula_symbols(formula) if values.get(sym) is None]
    if missing:
        return None
    expr = _FORMULA_TOKEN.sub(lambda m: repr(float(values[m.group(1).strip()])), formula)
    if not _SAFE_EXPR.match(expr):
        logger.warning(f"不合法的指標算式（代換後）: {expr[:80]}")
        return None
    try:
        return float(eval(expr, {"__builtins__": {}}, {}))
    except Exception as e:
        logger.warning(f"指標算式求值失敗 {formula}: {e}")
        return None


def _provider_of(item) -> str:
    return (getattr(item, "provider", None) or "yahoo").strip()


async def get_quotes_for_items(items: list) -> dict[str, dict]:
    """依 provider 取得所有指標的最新報價。

    回傳 {symbol: {price, change_percent, previous_close, last_updated}}。
    衍生指標（provider='derived'）在其他指標解析完之後才算，所以算式只能引用
    非衍生指標——不支援衍生指標互相引用（避免相依環，也沒有實際需求）。
    """
    from backend.services import rate_sources

    out: dict[str, dict] = {}

    # --- Yahoo ---
    yahoo_syms = [i.symbol for i in items if _provider_of(i) == "yahoo" and i.symbol]
    if yahoo_syms:
        for q in await get_market_quotes(yahoo_syms):
            out[q["symbol"]] = q

    # --- 官方來源（日本 MOF / ECB / BoE）---
    official = [i for i in items if rate_sources.is_supported(_provider_of(i))]
    if official:
        specs = [(_provider_of(i), i.provider_symbol or "") for i in official]
        series_map = await rate_sources.fetch_many(specs, days=400)
        for item in official:
            series = series_map.get((_provider_of(item), item.provider_symbol or "")) or []
            if not series:
                out[item.symbol] = {
                    "symbol": item.symbol, "price": None, "change_percent": 0,
                    "last_updated": None, "error": "來源無資料",
                }
                continue
            price = series[-1]["close"]
            prev = series[-2]["close"] if len(series) > 1 else None
            change_pct = ((price - prev) / prev * 100) if prev else 0
            out[item.symbol] = {
                "symbol": item.symbol,
                "price": round(price, 4),
                "change_percent": round(change_pct, 2),
                "previous_close": round(prev, 4) if prev is not None else None,
                "last_updated": series[-1]["time"],
            }

    # --- 衍生指標（利差等）---
    prices = {sym: q.get("price") for sym, q in out.items()}
    prevs = {sym: q.get("previous_close") for sym, q in out.items()}
    for item in items:
        if _provider_of(item) != "derived":
            continue
        price = eval_formula(item.formula or "", prices)
        prev = eval_formula(item.formula or "", prevs)
        change_pct = ((price - prev) / abs(prev) * 100) if (price is not None and prev) else 0
        out[item.symbol] = {
            "symbol": item.symbol,
            "price": round(price, 4) if price is not None else None,
            "change_percent": round(change_pct, 2),
            "previous_close": round(prev, 4) if prev is not None else None,
            "last_updated": datetime.utcnow().isoformat() if price is not None else None,
        }

    return out


async def get_history_for_item(item, period: str = "3mo", interval: str = "1d",
                               all_items: list | None = None) -> list[dict]:
    """依 provider 取得單一指標的歷史序列，格式一律 [{time, close}, ...]。

    *all_items* 只有衍生指標需要——要拿它算式引用到的其他指標的序列。
    """
    from backend.services import rate_sources

    provider = _provider_of(item)
    days = _period_to_days(period)

    if rate_sources.is_supported(provider):
        return await rate_sources.fetch_series(provider, item.provider_symbol or "", days=days)

    if provider == "derived":
        by_symbol = {i.symbol: i for i in (all_items or [])}
        syms = formula_symbols(item.formula or "")
        legs: dict[str, dict[str, float]] = {}
        for sym in syms:
            leg_item = by_symbol.get(sym)
            if leg_item is None:
                return []
            series = await get_history_for_item(leg_item, period, interval, all_items)
            legs[sym] = {p["time"][:10]: p["close"] for p in series}
        if not legs:
            return []
        # 只保留所有成分都有值的日期，避免某腿缺值算出假的跳空
        common = set.intersection(*[set(v.keys()) for v in legs.values()])
        rows = []
        for day in sorted(common):
            val = eval_formula(item.formula or "", {s: legs[s][day] for s in syms})
            if val is not None:
                rows.append({"time": day, "close": round(val, 4)})
        return rows

    return await get_market_history(item.symbol, period=period, interval=interval)


def _history_batch_sync(symbols: list[str], period: str, interval: str) -> dict[str, list[dict]]:
    """一次向 Yahoo 取多個代碼的歷史（yf.download 走批次，比逐一 Ticker.history 快得多）。"""
    out: dict[str, list[dict]] = {sym: [] for sym in symbols}
    if not symbols:
        return out
    try:
        df = yf.download(
            tickers=" ".join(symbols), period=period, interval=interval,
            group_by="ticker", auto_adjust=False, progress=False, threads=True,
        )
    except Exception as e:
        logger.error(f"yfinance batch history error: {e}")
        return out
    if df is None or df.empty:
        return out

    for sym in symbols:
        try:
            # 單一代碼時 yf.download 不會加 ticker 這層欄位索引
            sub = df[sym] if len(symbols) > 1 else df
            closes = sub["Close"].dropna()
            out[sym] = [
                {"time": idx.isoformat(), "close": round(float(val), 4)}
                for idx, val in closes.items()
            ]
        except Exception:
            out[sym] = []
    return out


async def get_histories_for_items(items: list, period: str = "3mo",
                                  interval: str = "1d") -> dict[str, list[dict]]:
    """批次取得多個指標的歷史序列，依 provider 分派。

    給 market_check 用：每小時一輪要算所有指標的 rolling 漲跌幅與區間條件，
    逐一抓會拖到幾十秒，Yahoo 端用 yf.download 一次抓完。
    """
    from backend.services import rate_sources

    out: dict[str, list[dict]] = {}

    yahoo_items = [i for i in items if _provider_of(i) == "yahoo" and i.symbol]
    if yahoo_items:
        syms = [i.symbol for i in yahoo_items]
        out.update(await asyncio.to_thread(_history_batch_sync, syms, period, interval))

    official = [i for i in items if rate_sources.is_supported(_provider_of(i))]
    if official:
        days = _period_to_days(period)
        specs = [(_provider_of(i), i.provider_symbol or "") for i in official]
        series_map = await rate_sources.fetch_many(specs, days=days)
        for item in official:
            out[item.symbol] = series_map.get(
                (_provider_of(item), item.provider_symbol or "")
            ) or []

    # 衍生指標：用上面已取得的成分序列逐日計算（只保留成分都有值的日期）
    for item in items:
        if _provider_of(item) != "derived":
            continue
        syms = formula_symbols(item.formula or "")
        legs = {sym: {p["time"][:10]: p["close"] for p in (out.get(sym) or [])} for sym in syms}
        if not legs or any(not v for v in legs.values()):
            out[item.symbol] = []
            continue
        common = set.intersection(*[set(v.keys()) for v in legs.values()])
        rows = []
        for day in sorted(common):
            val = eval_formula(item.formula or "", {sym: legs[sym][day] for sym in syms})
            if val is not None:
                rows.append({"time": day, "close": round(val, 4)})
        out[item.symbol] = rows

    return out


def _period_to_days(period: str) -> int:
    """把 yfinance 的 period 字串換算成天數（給官方來源的日頻序列用）。"""
    table = {"5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
             "1y": 365, "2y": 730, "5y": 1825, "max": 3650}
    return table.get(period, 90)
