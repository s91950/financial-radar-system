"""本地財經相關性篩選器（無 API 呼叫）。

使用 TF-IDF 近似評分判斷文章是否與金融市場相關。
核心詞命中權重 3×，輔助詞命中權重 1×，除以詞數開方做正規化。
"""

import math
import re

# ── 核心財經詞彙（命中分數 × 3）────────────────────────────────────────
# 中文：直接對應金融市場的詞彙
FINANCE_CORE_ZH = {
    # 股市 / 指數
    "股市", "股價", "股票", "A股", "台股", "港股", "日股", "陸股",
    "指數", "漲跌", "上漲", "下跌", "收盤", "開盤", "漲停", "跌停",
    "上市", "上櫃", "市值", "本益比", "殖利率", "融資", "融券",
    "道瓊", "那斯達克", "標普", "恒生", "日經", "上證", "深證",
    # 利率 / 貨幣政策
    "升息", "降息", "利率", "基準利率", "聯邦基金利率",
    "量化寬鬆", "QE", "縮表", "升息循環", "降息循環",
    "央行", "聯準會", "聯邦準備", "貨幣政策", "通膨目標",
    # 匯率 / 外匯
    "匯率", "台幣", "美元", "日圓", "歐元", "人民幣", "英鎊",
    "澳幣", "港幣", "外匯", "匯差", "升值", "貶值",
    # 債券 / 固定收益
    "債券", "公債", "國債", "殖利率", "10年期", "倒掛",
    "垃圾債", "投資等級", "信用評等", "穆迪", "標普評等", "惠譽",
    # 通膨 / 總體經濟
    "通膨", "通縮", "CPI", "PPI", "PCE", "GDP", "GNP",
    "就業", "失業", "非農", "薪資成長", "消費者信心",
    "衰退", "景氣", "緊縮", "刺激方案",
    # 金融機構 / 監管
    "銀行", "銀行業", "商業銀行", "投資銀行", "央行外匯",
    "金管會", "SEC", "Fed", "ECB", "BOJ", "BOE", "IMF", "BIS", "FSB",
    "金融穩定", "系統性風險", "壓力測試",
    # 大宗商品
    "原油", "油價", "黃金", "金價", "白銀", "銅價", "鋁價",
    "OPEC", "能源", "天然氣", "鐵礦石",
    # 投資工具
    "基金", "ETF", "期貨", "選擇權", "衍生性商品",
    "對沖基金", "私募股權", "風險資本", "REITs",
    # 企業財務
    "EPS", "營收", "獲利", "淨利", "毛利", "虧損", "財報",
    "季報", "年報", "除息", "現金股利", "股票股利",
    # 風險事件
    "破產", "違約", "債務危機", "流動性危機", "信用危機",
    "金融海嘯", "系統性", "金融風暴",
}

# 英文核心詞
FINANCE_CORE_EN = {
    # Equity markets
    "stock", "stocks", "equity", "equities", "shares", "nasdaq", "s&p500",
    "s&p", "dow", "nikkei", "hang seng", "sse", "etf", "ipo",
    "bull", "bear", "rally", "selloff", "correction", "volatility",
    # Rates / monetary policy
    "fed", "fomc", "federal reserve", "ecb", "boj", "boe",
    "interest rate", "rate hike", "rate cut", "taper", "qe",
    "quantitative easing", "monetary policy", "inflation target",
    # FX
    "forex", "currency", "dollar", "yen", "euro", "yuan", "sterling",
    "exchange rate", "devaluation", "appreciation",
    # Fixed income
    "bond", "bonds", "yield", "treasury", "gilt", "bund",
    "credit spread", "junk bond", "investment grade", "moody", "fitch",
    # Macro
    "inflation", "cpi", "ppi", "pce", "gdp", "unemployment",
    "nonfarm", "payroll", "recession", "stagflation",
    # Commodities
    "oil", "crude", "wti", "brent", "gold", "silver", "copper",
    "opec", "natural gas", "commodity",
    # Finance terms
    "bank", "banking", "central bank", "imf", "bis", "fsb",
    "liquidity", "systemic risk", "stress test", "bail out",
    # Corporate finance
    "earnings", "revenue", "profit", "loss", "eps", "dividend",
    "roe", "roa", "debt", "leverage", "default", "bankruptcy",
}

# ── 輔助財經詞彙（命中分數 × 1）────────────────────────────────────────
FINANCE_CONTEXT_ZH = {
    "經濟", "政策", "預算", "財政", "貿易", "出口", "進口", "順差", "逆差",
    "企業", "公司", "市場", "投資", "投資人", "分析師", "預測",
    "報告", "數據", "公布", "宣布", "調降", "調升", "預期",
    "合併", "收購", "裁員", "重組", "轉型", "擴張", "縮減",
    "科技股", "金融股", "傳產股", "半導體", "電子",
    "美國", "中國", "歐盟", "日本", "台灣",  # 配合財經詞語境有意義
}

FINANCE_CONTEXT_EN = {
    "economy", "economic", "policy", "budget", "fiscal", "trade",
    "export", "import", "surplus", "deficit", "market", "markets",
    "investor", "analyst", "forecast", "report", "data", "release",
    "merger", "acquisition", "layoff", "restructure",
    "china", "us", "europe", "japan", "taiwan",  # 財經語境
    "tech", "semiconductor", "financial",
}

# ── 非財經排除詞（單獨出現時降分）────────────────────────────────────────
NON_FINANCE_INDICATORS = {
    "體育", "娛樂", "演唱會", "電影", "電視劇", "追劇", "選秀",
    "足球", "籃球", "棒球", "網球", "奧運", "世界盃",
    "明星", "偶像", "八卦", "緋聞",
    "美食", "旅遊", "健康", "養生", "食譜",
    "sports", "entertainment", "celebrity", "movie", "concert",
    "football", "basketball", "olympics",
}

# ── 預建小寫版本（避免每次重算）────────────────────────────────────────
_CORE_ZH = FINANCE_CORE_ZH
_CORE_EN = {w.lower() for w in FINANCE_CORE_EN}
_CTX_ZH = FINANCE_CONTEXT_ZH
_CTX_EN = {w.lower() for w in FINANCE_CONTEXT_EN}
_NON_FIN = NON_FINANCE_INDICATORS


def compute_finance_relevance(title: str, content: str) -> float:
    """計算文章的財經相關性分數（0.0 ~ 1.0），完全本地計算，不呼叫任何 API。

    算法：
      text  = title（×3 加權到 core_hits）+ content 前 400 字
      core_hits    = 命中 FINANCE_CORE 詞彙的次數（中英文合計）
      context_hits = 命中 FINANCE_CONTEXT 詞彙的次數
      non_fin_hits = 命中 NON_FINANCE_INDICATORS 的次數
      word_count   = max(text.split() 詞數, 1)
      raw   = (core_hits × 3 + context_hits × 1 - non_fin_hits × 2) / sqrt(word_count)
      score = clip(raw, 0.0, 1.0)

    標題詞彙額外加 3× 權重：標題命中比內文命中更有意義。

    建議閾值：>= 0.15 視為相關（可在 SystemConfig 設定 finance_relevance_threshold）。
    """
    if not title:
        return 0.0

    # 標題文字（大小寫均保留，再轉小寫比對）
    title_lower = title.lower()
    # 內文前 400 字
    body = (content or "")[:400]
    body_lower = body.lower()

    # 合併文字供詞數計算（中文以字為單位，英文以空白切詞）
    full_text = title + " " + body
    full_lower = title_lower + " " + body_lower

    # 詞數估計：中文字數 + 英文詞數
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', full_text))
    en_words = len(re.findall(r'[A-Za-z]+', full_text))
    word_count = max(zh_chars // 2 + en_words, 1)  # 中文每 2 字算 1 詞

    # ── 計算命中分數 ────────────────────────────────────────────────────
    core_hits = 0
    context_hits = 0
    non_fin_hits = 0

    # 中文核心詞（在標題出現給額外加成）
    for kw in _CORE_ZH:
        in_title = kw in title
        in_body = kw in body
        if in_title:
            core_hits += 3  # 標題命中×3
        elif in_body:
            core_hits += 1

    # 英文核心詞
    for kw in _CORE_EN:
        in_title = kw in title_lower
        in_body = kw in body_lower
        if in_title:
            core_hits += 3
        elif in_body:
            core_hits += 1

    # 中文輔助詞
    for kw in _CTX_ZH:
        if kw in full_text:
            context_hits += 1

    # 英文輔助詞
    for kw in _CTX_EN:
        if kw in full_lower:
            context_hits += 1

    # 非財經詞（降分，但不超過 0）
    for kw in _NON_FIN:
        if kw in full_text or kw.lower() in full_lower:
            non_fin_hits += 1

    # ── 綜合計算 ────────────────────────────────────────────────────────
    raw = (core_hits * 3 + context_hits - non_fin_hits * 2) / math.sqrt(word_count)
    return max(0.0, min(raw, 1.0))
