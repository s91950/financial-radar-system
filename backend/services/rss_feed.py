"""RSS feed parser for monitoring official sources."""

import asyncio
import logging
import re
from datetime import datetime, timedelta

import feedparser
import httpx

logger = logging.getLogger(__name__)

# URL patterns that are known redirect wrappers (not actual article pages)
_REDIRECT_PATTERNS = (
    "feeds.reuters.com",
    "feeds.feedburner.com",
    "rss.sina.com.cn",
    "feeds.bloomberg.com",
    "feeds.a.dj.com",
    "feeds.marketwatch.com",
)


async def _resolve_redirect(url: str, client: httpx.AsyncClient) -> str:
    """Follow HTTP redirects to get the final article URL.

    Only resolves URLs that match known redirect-wrapper patterns to avoid
    unnecessary requests. Falls back to original URL on any error.
    Uses streaming GET (not HEAD) because some servers (e.g. Google News)
    only redirect on GET requests.
    """
    if not url:
        return url
    if not any(p in url for p in _REDIRECT_PATTERNS):
        return url
    try:
        async with client.stream("GET", url, follow_redirects=True, timeout=8) as resp:
            final = str(resp.url)
        # Sanity check: resolved URL should be http(s) and different from original
        if final.startswith("http") and final != url:
            return final
    except Exception:
        pass
    return url


async def _resolve_gn_article_urls(articles: list[dict]) -> list[dict]:
    """Decode news.google.com/rss/articles/... URLs to actual article URLs.

    Uses the same batchexecute decode as google_news.py.
    Articles without GN URLs are returned unchanged.
    Falls back to original URL on any decode failure.
    """
    from backend.services.google_news import _resolve_google_news_urls

    gn_indices = []
    gn_ids = []
    for i, a in enumerate(articles):
        url = a.get("source_url", "")
        if "news.google.com" in url and "/articles/" in url:
            art_id = url.split("/articles/")[-1].split("?")[0]
            if art_id:
                gn_indices.append(i)
                gn_ids.append(art_id)

    if not gn_ids:
        return articles

    try:
        async with httpx.AsyncClient(
            timeout=15, verify=False, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            decoded = await _resolve_google_news_urls(client, gn_ids)
        for pos, idx in enumerate(gn_indices):
            resolved = decoded[pos] if pos < len(decoded) else None
            if resolved and resolved.startswith("http"):
                articles[idx]["source_url"] = resolved
    except Exception as e:
        logger.warning(f"GN batchexecute decode failed: {e}")

    return articles


async def fetch_rss_feed(url: str, hours_back: int = 24) -> list[dict]:
    """Fetch and parse an RSS feed, returning recent entries."""
    try:
        async with httpx.AsyncClient(timeout=30, verify=False, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FinancialRadar/1.0)"})
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

        cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        articles = []

        # Clean up feed-level source name (e.g. '"site:imf.org when:7d" - Google News')
        from backend.services.google_news import _clean_source_name
        feed_source = _clean_source_name(feed.feed.get("title", url))

        for entry in feed.entries:
            published = _parse_date(entry)
            if published and published < cutoff:
                continue

            # For Google News RSS feeds, prefer entry-level <source> (accurate publisher)
            entry_source = entry.get("source", {}).get("title", "")
            article_source = _clean_source_name(entry_source) if entry_source else feed_source

            articles.append({
                "title": entry.get("title", "No title"),
                "content": _get_content(entry),
                "source": article_source,
                "source_url": entry.get("link", ""),
                "published_at": published.isoformat() if published else None,
                "category": "official",
            })

        # Resolve redirect URLs concurrently (only for known redirect patterns)
        if articles:
            async with httpx.AsyncClient(timeout=10, verify=False, follow_redirects=True) as resolve_client:
                resolved = await asyncio.gather(
                    *[_resolve_redirect(a["source_url"], resolve_client) for a in articles],
                    return_exceptions=True,
                )
            for i, r in enumerate(resolved):
                if isinstance(r, str):
                    articles[i]["source_url"] = r

            # Decode Google News article URLs (batchexecute API)
            articles = await _resolve_gn_article_urls(articles)

        return articles
    except Exception as e:
        logger.error(f"RSS feed error ({url}): {e}")
        return []


async def fetch_multiple_feeds(
    feeds: list[dict],
    hours_back: int = 24,
    global_topics: list[str] | None = None,
    return_raw: bool = False,
) -> list[dict] | tuple[list[dict], list[dict]]:
    """Fetch multiple RSS feeds and combine results (parallel).

    feeds: list of {"name": str, "url": str, "keywords": list[str]}
    global_topics: radar topic strings used as fallback (or supplement) when a feed has no
                   source-specific keywords, or when source keywords match nothing.
                   Each topic may use boolean AND/OR syntax: "(A OR B) C" means A-or-B AND C.
                   An article passes the fallback filter if it matches ANY topic.
    return_raw: if True, return (filtered_articles, all_raw_articles) tuple.
                Raw articles are unfiltered — used for topic cross-matching in RSS-only mode.

    Filter logic (OR semantics):
      - Source has keywords → match by source keywords; ALSO include any article matching
        global_topics that wasn't already captured (union, not exclusive).
      - Source has no keywords → match by global_topics only.
      - Neither → drop all (avoid noise).
    """
    # Fetch all feeds in parallel for speed
    # fetch_all 來源應讀取所有可用文章，不受 hours_back 限制。
    # 使用 48h 底限確保 RSS feed 中的歷史條目都能通過時間過濾；
    # 去重（URL/title）由 jobs.py 負責，不會重複儲存已有文章。
    def _feed_hours(f: dict) -> int:
        return max(hours_back, 48) if f.get("fetch_all") else hours_back

    raw_results = await asyncio.gather(
        *[fetch_rss_feed(f["url"], _feed_hours(f)) for f in feeds],
        return_exceptions=True,
    )

    all_articles = []
    all_raw: list[dict] = []  # unfiltered pool for topic cross-matching

    for feed_info, articles in zip(feeds, raw_results):
        if isinstance(articles, Exception):
            logger.error(f"RSS gather error ({feed_info['url']}): {articles}")
            articles = []

        # 用 MonitorSource.name 覆蓋 RSS feed 自帶的冗長標題（直接使用，不清洗）
        feed_name = feed_info.get("name")
        if feed_name:
            for a in articles:
                a["source"] = feed_name

        all_raw.extend(articles)  # collect before filtering

        source_kws = feed_info.get("keywords", [])
        fetch_all = feed_info.get("fetch_all", False)

        if fetch_all:
            # 全文讀取模式：納入所有文章，用 _annotate_matched_terms 標記實際出現的所有關鍵詞
            # 標記 fetch_all_source 讓財經篩選跳過這些文章（但仍計算分數）
            if source_kws:
                articles = [
                    {**a, "matched_keyword": _annotate_matched_terms(a, source_kws), "fetch_all_source": True}
                    for a in articles
                ]
            else:
                articles = [{**a, "fetch_all_source": True} for a in articles]
        elif source_kws:
            # Source-specific keywords: simple OR matching
            kw_matched = _filter_by_keywords(articles, source_kws)
            if global_topics:
                # Supplement with global topics (OR logic) — catch articles the narrow
                # source keywords may have missed
                kw_urls = {a["source_url"] for a in kw_matched}
                topic_extra = [
                    a for a in _filter_by_topic_strings(articles, global_topics)
                    if a["source_url"] not in kw_urls
                ]
                articles = kw_matched + topic_extra
            else:
                articles = kw_matched
        elif global_topics:
            # No source keywords — filter against radar topics with proper boolean semantics
            articles = _filter_by_topic_strings(articles, global_topics)
        else:
            # 無任何過濾條件 → 不納入，避免無關文章進入雷達
            articles = []
        all_articles.extend(articles)

    if return_raw:
        return all_articles, all_raw
    return all_articles


def _term_in_text(term: str, text_lower: str) -> bool:
    """Check if *term* appears in *text_lower* (caller must pre-lowercase the text).

    Pure-ASCII terms (English words, digits, hyphens) use word-boundary matching so
    "Coup" does NOT match "Couple" or "Recovery".  Multi-word ASCII phrases like
    "Trade war" are matched as a phrase (all words must be adjacent / exact phrase).
    CJK / mixed-script terms use simple substring matching (no word boundaries in Chinese).
    """
    t = term.strip().lower()
    if not t:
        return False
    if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9 \-]*$', t):
        # Word-boundary on left and right: prevents "Coup" matching "Couple"
        pattern = r'(?<![a-zA-Z0-9\-])' + re.escape(t) + r'(?![a-zA-Z0-9\-])'
        return bool(re.search(pattern, text_lower))
    return t in text_lower


def _strip_not_terms(topic: str) -> tuple[str, list[str]]:
    """Extract NOT exclusion terms from a topic string.

    Supports:  '...NOT term'  and  '...NOT "multi word"'
    Returns (cleaned_topic_without_not_clauses, [not_term, ...])
    """
    not_terms: list[str] = []
    # Quoted multi-word NOT first, then bare-word NOT
    for m in re.finditer(r'\bNOT\s+"([^"]+)"', topic, re.IGNORECASE):
        not_terms.append(m.group(1).strip())
    for m in re.finditer(r'\bNOT\s+(?!")((?:[^\s()"]+))', topic, re.IGNORECASE):
        not_terms.append(m.group(1).strip())
    cleaned = re.sub(r'\bNOT\s+(?:"[^"]+"|[^\s()"]+)\s*', '', topic, flags=re.IGNORECASE).strip()
    return cleaned, not_terms


def _parse_topic_groups(topic: str) -> list[list[str]]:
    """Parse a topic string into AND-groups of OR-terms.

    Examples:
      "(Fed OR FOMC) 升息"  → [["Fed","FOMC"], ["升息"]]
      "台積電 法說會"        → [["台積電"], ["法說會"]]
      "台股"               → [["台股"]]
    """
    raw_groups = re.findall(r'\(([^)]+)\)', topic)
    if raw_groups:
        groups: list[list[str]] = []
        for raw in raw_groups:
            terms = [t.strip().strip("\"'") for t in re.split(r'\bOR\b', raw, flags=re.IGNORECASE)]
            terms = [t for t in terms if t]
            if terms:
                groups.append(terms)
        # Bare words outside parentheses are also AND conditions
        bare = re.sub(r'\([^)]+\)', '', topic)
        bare = re.sub(r'\b(?:OR|AND)\b', ' ', bare, flags=re.IGNORECASE)
        for word in bare.split():
            word = word.strip().strip("\"'")
            if word:
                groups.append([word])
        return groups if groups else [[topic]]
    # No parentheses — space-separated words are AND groups
    words = [w.strip().strip("\"'") for w in topic.split()]
    words = [w for w in words if w]
    if not words:
        return [[topic]]
    if len(words) == 1:
        return [[words[0]]]
    return [[w] for w in words]


def _extract_display_kw(topic: str, text_lower: str, max_terms: int = 4) -> str:
    """從 topic 字串中取出真正出現在文章文字的詞，供 UI badge 顯示。

    排序規則（最多 max_terms 個）：
      第 1 批：每個 AND-group 各取第一個命中詞（依群組順序），確保各群組至少有代表
      第 2 批：繼續從各群組補充更多命中詞，填滿剩餘名額

    例：topic="(Fed OR FOMC) (升息 OR 降息)"，text 含 "FOMC" 和 "降息"
      → "FOMC / 降息"
    """
    clean_topic, _ = _strip_not_terms(topic)  # strip NOT before group parsing
    groups = _parse_topic_groups(clean_topic) if clean_topic else []
    seen: set[str] = set()
    result: list[str] = []

    # 第 1 批：每個 AND-group 的第一個命中詞
    for group in groups:
        rep = next((t for t in group if _term_in_text(t, text_lower)), None)
        if rep and rep not in seen:
            seen.add(rep)
            result.append(rep)
        if len(result) >= max_terms:
            break

    # 第 2 批：各群組中額外命中詞填滿剩餘名額
    if len(result) < max_terms:
        for group in groups:
            for term in group:
                if _term_in_text(term, text_lower) and term not in seen:
                    seen.add(term)
                    result.append(term)
                    if len(result) >= max_terms:
                        break
            if len(result) >= max_terms:
                break

    return ' / '.join(result)


def _filter_by_topic_strings(articles: list[dict], topics: list[str]) -> list[dict]:
    """Filter articles against radar topic strings, preserving boolean AND/OR/NOT semantics.

    Each topic may be:
      - A plain keyword: "台股"       → matches if "台股" appears
      - A boolean group: "(Fed OR FOMC) 升息" → (Fed or FOMC) AND 升息 both appear
      - With exclusion:  "(Fed OR FOMC) 升息 NOT 廣告" → above AND "廣告" absent

    ASCII terms use whole-word matching; CJK terms use substring matching.
    An article passes if it matches ANY topic in the list.
    """
    def _matches_topic(tl: str, topic: str) -> bool:
        clean, not_terms = _strip_not_terms(topic)
        if not_terms and any(_term_in_text(nt, tl) for nt in not_terms):
            return False
        if not clean:
            return True
        groups = _parse_topic_groups(clean)
        return all(any(_term_in_text(term, tl) for term in group) for group in groups)

    filtered = []
    for article in articles:
        tl = f"{article.get('title', '')} {article.get('content', '')}".lower()
        for topic in topics:
            if _matches_topic(tl, topic):
                display_kw = _extract_display_kw(topic, tl) or topic
                filtered.append({**article, "matched_keyword": display_kw})
                break
    return filtered


def _filter_by_keywords(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Filter articles by source-specific keywords using the same boolean syntax as global topics.

    Supported syntax (same as radar topic strings):
      - Plain keyword:    "台股"         → must appear in text
      - Space = AND:      "台積電 法說會" → both terms must appear
      - OR group:         "(Fed OR FOMC)" → either term must appear
      - Mixed:            "(Fed OR FOMC) 升息" → (Fed or FOMC) AND 升息 must appear

    An article passes if ANY keyword in the list matches.
    Sets matched_keyword on each passing article for downstream severity assessment.
    """
    return _filter_by_topic_strings(articles, keywords)


def _annotate_matched_terms(article: dict, keywords: list[str], max_total: int = 6) -> str | None:
    """For fetch_all mode: collect ALL matching terms from ALL source keywords for badge display.

    Unlike _filter_by_keywords (which stops at first match), this iterates every keyword
    and calls _extract_display_kw to find which specific terms actually appear in the text.
    Results are deduplicated and combined across all keywords.

    Important: for boolean AND keywords like "(BIS OR IMF) (降評 OR 警告)", BOTH AND-groups
    must have at least one hit before any terms are shown. This prevents partial AND-matches
    from generating misleading badges (e.g. showing "IMF" for an article that mentions IMF
    in passing but has nothing to do with 降評/警告).

    Example: keywords=["(台幣 OR 日幣) (升值 OR 貶值)"], article contains "台幣" and "升值"
      → Both AND-groups satisfied → Batch 1 picks first hit per group: "台幣", "升值"
      → Result: "台幣 / 升值"
    If article also contains "日幣":
      → Batch 2 fills remaining slot from group 0: "日幣"
      → Result: "台幣 / 升值 / 日幣"
    If article contains "IMF" but NOT any of 降評/警告:
      → AND condition not fully satisfied → skip, no badge
    """
    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    seen: set[str] = set()
    all_terms: list[str] = []

    for kw in keywords:
        # 布林 AND 條件必須所有群組都有命中才標記，避免單邊命中產生誤導性標籤
        clean_kw, not_terms = _strip_not_terms(kw)
        if not_terms and any(_term_in_text(nt, text) for nt in not_terms):
            continue
        groups = _parse_topic_groups(clean_kw) if clean_kw else []
        if groups and not all(any(_term_in_text(term, text) for term in group) for group in groups):
            continue

        kw_terms_str = _extract_display_kw(kw, text, max_terms=max_total)
        if not kw_terms_str:
            continue
        for term in kw_terms_str.split(' / '):
            term = term.strip()
            if term and term not in seen:
                seen.add(term)
                all_terms.append(term)
                if len(all_terms) >= max_total:
                    break
        if len(all_terms) >= max_total:
            break

    return ' / '.join(all_terms) if all_terms else None


def _parse_date(entry) -> datetime | None:
    """Parse published date from RSS entry.

    feedparser returns published_parsed as UTC struct_time.
    calendar.timegm() treats input as UTC (unlike mktime which assumes local time),
    so the result is comparable with datetime.utcnow().
    """
    import calendar
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.utcfromtimestamp(calendar.timegm(parsed))
            except Exception:
                continue
    return None


def _get_content(entry) -> str:
    """Extract content from RSS entry."""
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    return entry.get("summary", entry.get("description", ""))
