"""主題追蹤比對邏輯（新聞 + 市場警示共用）。

架構定位：主題是**純分類層**。文章由雷達以「全域關鍵字 + 來源關鍵字」抓進來之後，
才用主題關鍵字在這裡做歸類；主題關鍵字本身不參與抓取。

關鍵字語意（與 SearchPage 的 UI 呈現一致）：
  Topic.keywords 是一個 list，**條目之間是 OR**（任一條目成立即命中）。
  單一條目內部支援：
    - "(A OR B) (C OR D)"  → 群組之間 AND、群組內 OR
    - "台積電 法說會"        → 兩個裸詞 AND
    - "... NOT 廣告"        → NOT 排除詞
    - 純 ASCII 詞用詞邊界比對（"Coup" 不會命中 "Couple"）
  以上行為直接沿用 services.rss_feed 的 helper，與雷達 / RSS 篩選同一套。
"""

from backend.services.rss_feed import (
    _extract_display_kw,
    _parse_topic_groups,
    _strip_not_terms,
    _term_in_text,
)


def entry_matches(entry: str, text_lower: str) -> bool:
    """單一關鍵字條目是否命中（AND 群組 + NOT 排除 + 詞邊界）。"""
    clean, not_terms = _strip_not_terms(entry or "")
    if not_terms and any(_term_in_text(nt, text_lower) for nt in not_terms):
        return False
    if not clean.strip():
        return False
    groups = _parse_topic_groups(clean)
    if not groups:
        return False
    return all(any(_term_in_text(term, text_lower) for term in group) for group in groups)


def topic_matches(keywords: list[str], text_lower: str) -> bool:
    """任一關鍵字條目成立即算此主題命中。"""
    return any(entry_matches(kw, text_lower) for kw in (keywords or []))


def matched_keyword(keywords: list[str], text_lower: str, max_terms: int = 4) -> str:
    """回傳命中的顯示用關鍵字（取第一個成立的條目萃取），供 UI badge 使用。"""
    for kw in (keywords or []):
        if entry_matches(kw, text_lower):
            clean, _ = _strip_not_terms(kw)
            return _extract_display_kw(clean, text_lower, max_terms=max_terms)
    return ""


def article_text(article) -> str:
    """把文章（dict 或 ORM 物件）攤平成比對用的小寫文字。"""
    if isinstance(article, dict):
        title = article.get("title") or ""
        content = article.get("content") or ""
    else:
        title = getattr(article, "title", "") or ""
        content = getattr(article, "content", "") or ""
    return f"{title} {content[:2000]}".lower()


def signal_text(item, cond=None, extra: str = "") -> str:
    """把市場指標 + 觸發條件攤平成比對用的小寫文字。

    指標名稱 / 代碼 / 說明 + 條件名稱 / 觸發訊息 都納入，讓主題關鍵字
    （例如「殖利率」）能命中「美10Y殖利率」這類指標。
    """
    parts = [
        getattr(item, "name", "") or "",
        getattr(item, "symbol", "") or "",
        getattr(item, "description", "") or "",
        getattr(item, "category", "") or "",
    ]
    if cond is not None:
        parts.append(getattr(cond, "name", "") or "")
        parts.append(getattr(cond, "message", "") or "")
    if extra:
        parts.append(extra)
    return " ".join(p for p in parts if p).lower()
