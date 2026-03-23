"""Position exposure matching engine.

Matches user positions (from Google Sheets) against news articles
to determine which positions may be affected.
"""

import re

# Category keyword mapping for broad matching
CATEGORY_KEYWORDS = {
    "股票": ["stock", "equity", "股市", "股票", "指數", "nasdaq", "s&p", "道瓊", "台股"],
    "債券": ["bond", "treasury", "yield", "殖利率", "債券", "公債", "利率", "fed", "央行"],
    "債券ETF": ["bond", "treasury", "yield", "殖利率", "債券", "利率", "tlt", "bnd"],
    "ETF": ["etf", "基金"],
    "原物料": ["commodity", "oil", "gold", "原油", "黃金", "原物料", "白銀", "silver"],
    "加密貨幣": ["crypto", "bitcoin", "ethereum", "比特幣", "以太", "加密"],
    "外匯": ["forex", "currency", "匯率", "美元", "dollar", "日圓", "歐元"],
}


def match_positions_to_news(
    positions: list[dict],
    articles: list[dict],
) -> list[dict]:
    """Match positions against articles by symbol, name, and category keywords.

    Returns list of matched positions with relevance info:
    [{"position": {...}, "relevance_score": int, "matched_keywords": [...]}]
    """
    if not positions or not articles:
        return []

    # Build search text from all articles
    combined_text = " ".join(
        f"{a.get('title', '')} {a.get('content', '')[:300]}"
        for a in articles
    ).lower()

    matched = []
    for pos in positions:
        symbol = (pos.get("symbol") or "").strip()
        name = (pos.get("name") or "").strip()
        category = (pos.get("category") or "").strip()
        keywords_found = []
        score = 0

        # 1. Direct symbol match (highest relevance)
        if symbol and _word_in_text(symbol.lower(), combined_text):
            keywords_found.append(symbol)
            score += 3

        # 2. Name match
        if name and len(name) >= 2 and name.lower() in combined_text:
            keywords_found.append(name)
            score += 2

        # 3. Category broad match
        cat_kws = CATEGORY_KEYWORDS.get(category, [])
        for kw in cat_kws:
            if kw.lower() in combined_text:
                if kw not in keywords_found:
                    keywords_found.append(kw)
                score += 0.5
                break  # One category match is enough

        if score > 0:
            matched.append({
                "position": pos,
                "relevance_score": score,
                "matched_keywords": keywords_found,
            })

    # Sort by relevance (highest first)
    matched.sort(key=lambda x: x["relevance_score"], reverse=True)
    return matched


def format_exposure_summary(matched: list[dict]) -> str:
    """Format matched positions into a readable summary string."""
    if not matched:
        return ""

    lines = []
    for m in matched[:5]:  # Top 5
        pos = m["position"]
        symbol = pos.get("symbol", "")
        name = pos.get("name", "")
        qty = pos.get("quantity")
        avg = pos.get("avg_cost")
        cat = pos.get("category", "")

        parts = [f"{name} ({symbol})"]
        if qty:
            parts.append(f"{qty}股")
        if avg:
            parts.append(f"均價{avg}")
        if cat:
            parts.append(cat)

        lines.append("- " + " ".join(parts))

    return "\n".join(lines)


def _word_in_text(word: str, text: str) -> bool:
    """Check if word appears in text, handling symbols like ^GSPC, 2330.TW."""
    # Remove special chars for matching
    clean_word = re.sub(r"[^a-z0-9]", "", word)
    if len(clean_word) < 2:
        return False
    return clean_word in re.sub(r"[^a-z0-9\s]", "", text)
