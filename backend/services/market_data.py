"""Market data service using Yahoo Finance and TWSE API."""

import logging
from datetime import datetime

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)


async def get_market_quotes(symbols: list[str]) -> list[dict]:
    """Fetch current market data for a list of symbols via yfinance."""
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


async def get_market_history(symbol: str, period: str = "5d", interval: str = "1h") -> list[dict]:
    """Fetch historical market data for charting."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        return [
            {
                "time": idx.isoformat(),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
            for idx, row in hist.iterrows()
        ]
    except Exception as e:
        logger.error(f"yfinance history error ({symbol}): {e}")
        return []


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
