"""
簡單規則式命名實體識別（NER）
不依賴外部 NLP 套件，使用 regex + 字典比對。
"""
import re
from typing import Optional

# 央行與主要機構清單
_CENTRAL_BANKS = [
    "Fed", "Federal Reserve", "聯準會", "美聯儲",
    "FOMC", "ECB", "歐洲央行",
    "BOJ", "日本銀行", "日銀",
    "BOE", "英格蘭銀行",
    "PBOC", "人行", "人民銀行",
    "央行", "中央銀行",
    "BIS", "IMF", "World Bank", "世界銀行",
    "Fed Reserve",
]

# 常見貨幣清單（中英文）
_CURRENCIES = [
    "USD", "美元",
    "JPY", "日圓", "日元",
    "EUR", "歐元",
    "CNY", "人民幣", "RMB",
    "TWD", "台幣", "新台幣",
    "GBP", "英鎊",
    "KRW", "韓圓",
    "HKD", "港幣",
    "AUD", "澳幣",
    "CHF", "瑞士法郎",
    "BTC", "比特幣",
    "ETH", "以太幣",
]

# 台股代碼：4~5 位純數字，前後不接英文字母
_TW_STOCK_PATTERN = re.compile(r'(?<![A-Za-z])(\d{4,5})(?![A-Za-z])')

# 美股 ticker：2~5 個大寫英文字母，常見格式
_US_TICKER_PATTERN = re.compile(r'\b([A-Z]{2,5})\b')

# 已知常見美股 ticker 白名單（避免誤判英文縮寫）
_US_TICKER_WHITELIST = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "INTC", "QCOM", "AVGO", "TSM", "ASML",
    "JPM", "BAC", "GS", "MS", "C",
    "SPY", "QQQ", "DIA", "IWM", "TLT", "GLD", "SLV", "USO",
    "VIX", "DXY",
    "BTC", "ETH",
    "S&P", "NASDAQ", "DOW",
}


def extract_entities(text: str, positions: Optional[list] = None) -> dict:
    """
    從文字中抽取命名實體。

    Args:
        text: 要分析的文字（標題 + 內文片段）
        positions: 持倉清單，每筆為 dict，含 'symbol' 和 'name' 欄位

    Returns:
        dict with keys:
            stock_codes: list[str]   台股代碼
            us_tickers: list[str]    美股 ticker
            companies: list[str]     從 positions 比對到的公司名
            central_banks: list[str] 央行與主要機構
            currencies: list[str]    貨幣
    """
    result = {
        "stock_codes": [],
        "us_tickers": [],
        "companies": [],
        "central_banks": [],
        "currencies": [],
    }

    if not text:
        return result

    # 台股代碼
    tw_codes = _TW_STOCK_PATTERN.findall(text)
    result["stock_codes"] = list(dict.fromkeys(tw_codes))  # 去重保序

    # 美股 ticker（白名單過濾）
    us_matches = _US_TICKER_PATTERN.findall(text)
    result["us_tickers"] = list(dict.fromkeys(
        t for t in us_matches if t in _US_TICKER_WHITELIST
    ))

    # 央行 / 機構
    found_banks = []
    text_lower = text.lower()
    for bank in _CENTRAL_BANKS:
        if bank.lower() in text_lower:
            found_banks.append(bank)
    result["central_banks"] = list(dict.fromkeys(found_banks))

    # 貨幣
    found_currencies = []
    for currency in _CURRENCIES:
        if currency in text:
            found_currencies.append(currency)
    result["currencies"] = list(dict.fromkeys(found_currencies))

    # 從持倉清單比對公司名
    if positions:
        found_companies = []
        for pos in positions:
            name = pos.get("name", "")
            symbol = pos.get("symbol", "")
            if name and len(name) >= 2 and name in text:
                found_companies.append(name)
            elif symbol and len(symbol) >= 2 and symbol in text:
                found_companies.append(symbol)
        result["companies"] = list(dict.fromkeys(found_companies))

    return result


def format_entities_summary(entities: dict) -> str:
    """
    將 entities dict 格式化為簡短摘要字串，供通知或 log 使用。
    """
    parts = []
    if entities.get("companies"):
        parts.append("公司: " + "、".join(entities["companies"][:5]))
    if entities.get("stock_codes"):
        parts.append("代碼: " + " ".join(entities["stock_codes"][:5]))
    if entities.get("us_tickers"):
        parts.append("美股: " + " ".join(entities["us_tickers"][:5]))
    if entities.get("central_banks"):
        parts.append("機構: " + "、".join(entities["central_banks"][:3]))
    if entities.get("currencies"):
        parts.append("貨幣: " + " ".join(entities["currencies"][:4]))
    return " | ".join(parts) if parts else ""
