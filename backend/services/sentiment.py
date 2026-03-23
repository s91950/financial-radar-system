"""Market sentiment analysis engine.

Simple keyword-frequency-based sentiment scoring by market category.
"""

POSITIVE_KEYWORDS = [
    "rally", "surge", "上漲", "利多", "成長", "復甦", "走高", "反彈",
    "突破", "創高", "看漲", "買超", "加碼", "upgrade", "bullish",
    "recovery", "growth", "gain", "rise", "boost", "optimism",
]

NEGATIVE_KEYWORDS = [
    "crash", "plunge", "下跌", "利空", "衰退", "危機", "崩盤", "暴跌",
    "走低", "重挫", "看跌", "賣超", "減碼", "downgrade", "bearish",
    "recession", "decline", "loss", "fall", "slump", "fear", "risk",
    "制裁", "戰爭", "violation", "default", "bankruptcy",
]

CATEGORY_KEYWORDS = {
    "equity": ["股市", "stock", "s&p", "nasdaq", "台股", "道瓊", "指數",
               "上證", "恒生", "nikkei", "equity", "shares"],
    "bond": ["債券", "bond", "yield", "殖利率", "treasury", "公債",
             "利率", "fed", "央行", "升息", "降息", "rate"],
    "currency": ["匯率", "dollar", "美元", "日圓", "forex", "歐元",
                 "currency", "exchange rate", "台幣", "人民幣", "英鎊"],
    "commodity": ["原油", "oil", "黃金", "gold", "原物料", "白銀",
                  "silver", "copper", "commodity", "opec", "能源"],
    "crypto": ["bitcoin", "比特幣", "crypto", "以太", "ethereum",
               "blockchain", "加密貨幣", "defi", "nft"],
}

CATEGORY_LABELS = {
    "equity": "股市",
    "bond": "債市",
    "currency": "匯市",
    "commodity": "原物料",
    "crypto": "加密貨幣",
}


def analyze_sentiment(articles: list[dict]) -> list[dict]:
    """Analyze articles and return per-category heat and sentiment.

    Returns:
        [{category, label, heat, sentiment, sentiment_label, article_count, top_keywords}]
    """
    if not articles:
        return []

    # Categorize each article
    categorized: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_KEYWORDS}
    uncategorized = []

    for article in articles:
        text = (
            f"{article.get('title', '')} {(article.get('content', '') or '')[:300]}"
        ).lower()

        matched_cat = None
        best_score = 0
        for cat, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                matched_cat = cat

        if matched_cat and best_score > 0:
            categorized[matched_cat].append(article)
        else:
            uncategorized.append(article)

    # Calculate sentiment per category
    results = []
    max_count = max((len(arts) for arts in categorized.values()), default=1) or 1

    for cat, arts in categorized.items():
        if not arts:
            results.append({
                "category": cat,
                "label": CATEGORY_LABELS.get(cat, cat),
                "heat": 0,
                "sentiment": 0,
                "sentiment_label": "neutral",
                "article_count": 0,
                "top_keywords": [],
            })
            continue

        # Sentiment score per article
        pos_total = 0
        neg_total = 0
        keyword_counts: dict[str, int] = {}

        for article in arts:
            text = (
                f"{article.get('title', '')} {(article.get('content', '') or '')[:300]}"
            ).lower()

            for kw in POSITIVE_KEYWORDS:
                if kw in text:
                    pos_total += 1
            for kw in NEGATIVE_KEYWORDS:
                if kw in text:
                    neg_total += 1

            # Track keywords for this category
            for kw in CATEGORY_KEYWORDS[cat]:
                if kw in text:
                    keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

        # Normalize: heat = article_count / max_count * 100
        heat = round(len(arts) / max_count * 100)

        # Sentiment: range [-1, 1]
        total_signals = pos_total + neg_total
        if total_signals > 0:
            sentiment = round((pos_total - neg_total) / total_signals, 2)
        else:
            sentiment = 0

        # Label
        if sentiment > 0.2:
            sentiment_label = "positive"
        elif sentiment < -0.2:
            sentiment_label = "negative"
        else:
            sentiment_label = "neutral"

        # Top keywords
        top_kws = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        results.append({
            "category": cat,
            "label": CATEGORY_LABELS.get(cat, cat),
            "heat": heat,
            "sentiment": sentiment,
            "sentiment_label": sentiment_label,
            "article_count": len(arts),
            "top_keywords": [kw for kw, _ in top_kws],
        })

    # Sort by article count (most active first)
    results.sort(key=lambda x: x["article_count"], reverse=True)
    return results
