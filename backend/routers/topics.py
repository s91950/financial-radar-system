"""Router for Module: 主題追蹤 (Topic Tracking)."""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import (
    Alert,
    Article,
    MarketWatchItem,
    Topic,
    TopicArticle,
    TopicSignal,
    get_db,
)
from backend.services import topic_match

router = APIRouter()

def _assess_article_severity(title: str, content: str, crit_kws: list, high_kws: list) -> str:
    """Assess severity using user-configured keyword lists (loaded from DB by caller)."""
    text = (title + " " + (content or "")[:200]).lower()
    if any(kw in text for kw in crit_kws):
        return "critical"
    if any(kw in text for kw in high_kws):
        return "high"
    return "low"


# --- Pydantic Models ---

class TopicCreate(BaseModel):
    name: str
    keywords: list[str] = []
    bound_symbols: list[str] = []   # 手動綁定的市場指標代碼


class TopicUpdate(BaseModel):
    name: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None
    bound_symbols: list[str] | None = None


class SearchImportRequest(BaseModel):
    hours_back: int = 24  # 1 | 3 | 6 | 12 | 24 | 48 | 72 | 168


class RematchRequest(BaseModel):
    """回溯比對：拿既有資料重跑此主題的關鍵字比對。"""
    days: int = 7             # 回溯天數（新聞看 fetched_at、市場警示看 created_at）
    include_signals: bool = True


# --- Helpers ---

def _json_list(value) -> list:
    try:
        return json.loads(value) if value else []
    except Exception:
        return []


def _topic_to_dict(
    topic: Topic,
    article_count: int | None = None,
    signal_count: int | None = None,
) -> dict:
    return {
        "id": topic.id,
        "name": topic.name,
        "keywords": _json_list(topic.keywords),
        "bound_symbols": _json_list(topic.bound_symbols),
        "is_active": topic.is_active,
        "created_at": (topic.created_at.isoformat() + "Z") if topic.created_at else None,
        "article_count": article_count if article_count is not None else len(topic.articles),
        "signal_count": signal_count if signal_count is not None else len(topic.signals),
    }


def _signal_to_dict(sig: TopicSignal) -> dict:
    return {
        "id": sig.id,
        "topic_id": sig.topic_id,
        "alert_id": sig.alert_id,
        "symbol": sig.symbol,
        "name": sig.name,
        "title": sig.title,
        "message": sig.message,
        "value": sig.value,
        "change_value": sig.change_value,
        "change_unit": sig.change_unit,
        "change_window": sig.change_window,
        "severity": sig.severity,
        "signal": sig.signal,
        "matched_keyword": sig.matched_keyword,
        "add_source": sig.add_source,
        "triggered_at": (sig.triggered_at.isoformat() + "Z") if sig.triggered_at else None,
        "added_at": (sig.added_at.isoformat() + "Z") if sig.added_at else None,
    }


def _article_to_dict(a: TopicArticle, crit_kws: list, high_kws: list) -> dict:
    return {
        "id": a.id,
        "topic_id": a.topic_id,
        "title": a.title,
        "content": a.content,
        "source": a.source,
        "source_url": a.source_url,
        "published_at": (a.published_at.isoformat() + "Z") if a.published_at else None,
        "added_at": (a.added_at.isoformat() + "Z") if a.added_at else None,
        "add_source": a.add_source,
        "matched_keyword": a.matched_keyword,
        "severity": _assess_article_severity(a.title or "", a.content or "", crit_kws, high_kws),
    }


# --- CRUD endpoints ---

@router.get("/")
async def get_topics(db: Session = Depends(get_db)):
    """Get all topics with article counts."""
    topics = db.query(Topic).order_by(Topic.created_at.desc()).all()
    result = []
    for t in topics:
        count = db.query(TopicArticle).filter(TopicArticle.topic_id == t.id).count()
        sig_count = db.query(TopicSignal).filter(TopicSignal.topic_id == t.id).count()
        result.append(_topic_to_dict(t, count, sig_count))
    return result


@router.post("/")
async def create_topic(req: TopicCreate, db: Session = Depends(get_db)):
    """Create a new tracking topic."""
    topic = Topic(
        name=req.name,
        keywords=json.dumps(req.keywords, ensure_ascii=False),
        bound_symbols=json.dumps(req.bound_symbols, ensure_ascii=False),
        is_active=True,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return _topic_to_dict(topic, 0, 0)


@router.put("/{topic_id}")
async def update_topic(topic_id: int, req: TopicUpdate, db: Session = Depends(get_db)):
    """Update topic name, keywords or active state."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {"error": "Topic not found"}
    if req.name is not None:
        topic.name = req.name
    if req.keywords is not None:
        topic.keywords = json.dumps(req.keywords, ensure_ascii=False)
    if req.is_active is not None:
        topic.is_active = req.is_active
    if req.bound_symbols is not None:
        topic.bound_symbols = json.dumps(req.bound_symbols, ensure_ascii=False)
    db.commit()
    count = db.query(TopicArticle).filter(TopicArticle.topic_id == topic_id).count()
    sig_count = db.query(TopicSignal).filter(TopicSignal.topic_id == topic_id).count()
    return _topic_to_dict(topic, count, sig_count)


@router.delete("/{topic_id}")
async def delete_topic(topic_id: int, db: Session = Depends(get_db)):
    """Delete a topic and all its articles."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {"error": "Topic not found"}
    db.delete(topic)
    db.commit()
    return {"success": True}


# --- Articles ---

@router.get("/{topic_id}/articles")
async def get_topic_articles(
    topic_id: int,
    limit: int = Query(100, ge=1, le=500),
    add_source: str | None = None,  # 'radar' | 'manual'
    db: Session = Depends(get_db),
):
    """Get articles for a topic, newest first."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {"error": "Topic not found"}

    q = db.query(TopicArticle).filter(TopicArticle.topic_id == topic_id)
    if add_source:
        q = q.filter(TopicArticle.add_source == add_source)
    articles = q.order_by(TopicArticle.added_at.desc()).limit(limit).all()

    radar_count = db.query(TopicArticle).filter(
        TopicArticle.topic_id == topic_id, TopicArticle.add_source == "radar"
    ).count()
    manual_count = db.query(TopicArticle).filter(
        TopicArticle.topic_id == topic_id, TopicArticle.add_source == "manual"
    ).count()

    # 市場數據警示（與新聞並列的第二種內容）
    signals = (
        db.query(TopicSignal)
        .filter(TopicSignal.topic_id == topic_id)
        .order_by(TopicSignal.triggered_at.desc())
        .limit(limit)
        .all()
    )
    signal_count = db.query(TopicSignal).filter(TopicSignal.topic_id == topic_id).count()

    from backend.routers.settings import get_severity_keywords
    crit_kws, high_kws = get_severity_keywords(db)

    return {
        "topic": _topic_to_dict(topic, radar_count + manual_count, signal_count),
        "articles": [_article_to_dict(a, crit_kws, high_kws) for a in articles],
        "signals": [_signal_to_dict(sg) for sg in signals],
        "stats": {
            "radar": radar_count,
            "manual": manual_count,
            "total": radar_count + manual_count,
            "signals": signal_count,
        },
    }


@router.get("/market-symbols")
async def list_market_symbols(db: Session = Depends(get_db)):
    """可供主題綁定的市場指標清單（給主題編輯頁的勾選 UI）。"""
    items = db.query(MarketWatchItem).order_by(
        MarketWatchItem.category, MarketWatchItem.sort_order
    ).all()
    return [
        {
            "symbol": i.symbol,
            "name": i.name,
            "category": i.category,
            "description": i.description,
        }
        for i in items
    ]


@router.delete("/{topic_id}/signals/{signal_id}")
async def delete_topic_signal(topic_id: int, signal_id: int, db: Session = Depends(get_db)):
    """從主題移除一則市場警示（不影響原始 Alert）。"""
    sig = db.query(TopicSignal).filter(
        TopicSignal.id == signal_id, TopicSignal.topic_id == topic_id
    ).first()
    if not sig:
        return {"error": "Signal not found"}
    db.delete(sig)
    db.commit()
    return {"success": True}


@router.post("/{topic_id}/rematch")
async def rematch_topic(topic_id: int, req: RematchRequest, db: Session = Depends(get_db)):
    """回溯比對：拿既有的新聞與市場警示重跑此主題的關鍵字比對。

    新建主題 / 改完關鍵字後用來補齊歷史資料——平時的自動歸類只作用於
    每次掃描新收到的文章，不會回頭看既有資料。
    """
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {"error": "Topic not found"}

    keywords = _json_list(topic.keywords)
    bound = _json_list(topic.bound_symbols)
    if not keywords and not bound:
        return {"error": "此主題尚未設定關鍵字或綁定指標", "articles": 0, "signals": 0}

    days = max(1, min(req.days, 90))
    cutoff = datetime.utcnow() - timedelta(days=days)

    # --- 新聞 ---
    imported = 0
    if keywords:
        existing_urls = {
            row[0] for row in
            db.query(TopicArticle.source_url).filter(TopicArticle.topic_id == topic_id).all()
            if row[0]
        }
        candidates = (
            db.query(Article)
            .filter(Article.fetched_at >= cutoff)
            .order_by(Article.fetched_at.desc())
            .limit(5000)
            .all()
        )
        for art in candidates:
            url = art.source_url or ""
            if not url or url in existing_urls:
                continue
            text = topic_match.article_text(art)
            if not topic_match.topic_matches(keywords, text):
                continue
            existing_urls.add(url)
            db.add(TopicArticle(
                topic_id=topic_id,
                title=art.title or "",
                content=art.content or "",
                source=art.source or "",
                source_url=url,
                published_at=art.published_at,
                add_source="radar",
                matched_keyword=topic_match.matched_keyword(keywords, text) or None,
            ))
            imported += 1

    # --- 市場警示 ---
    sig_imported = 0
    if req.include_signals:
        existing_alert_ids = {
            row[0] for row in
            db.query(TopicSignal.alert_id).filter(TopicSignal.topic_id == topic_id).all()
            if row[0]
        }
        watch_by_name = {w.name: w for w in db.query(MarketWatchItem).all()}
        alerts = (
            db.query(Alert)
            .filter(Alert.type == "market", Alert.created_at >= cutoff)
            .order_by(Alert.created_at.desc())
            .limit(1000)
            .all()
        )
        for al in alerts:
            if al.id in existing_alert_ids:
                continue
            text = f"{al.title or ''} {al.content or ''}".lower()
            # 找出這則警示對應的指標（標題格式："📊 {name} — {message}"）
            item = next((w for n, w in watch_by_name.items() if n and n in (al.title or "")), None)
            add_source = None
            matched_kw = ""
            if item is not None and item.symbol in bound:
                add_source = "bound"
            elif keywords and topic_match.topic_matches(keywords, text):
                add_source = "keyword"
                matched_kw = topic_match.matched_keyword(keywords, text)
            if not add_source:
                continue
            existing_alert_ids.add(al.id)
            db.add(TopicSignal(
                topic_id=topic_id,
                alert_id=al.id,
                symbol=item.symbol if item is not None else "",
                name=item.name if item is not None else (al.source or "Market"),
                title=al.title or "",
                message=al.content or "",
                value=item.current_value if item is not None else None,
                severity=al.severity,
                signal=item.signal_status if item is not None else None,
                matched_keyword=matched_kw or None,
                triggered_at=al.created_at,
                add_source=add_source,
            ))
            sig_imported += 1

    db.commit()
    return {"articles": imported, "signals": sig_imported, "days": days}


@router.delete("/{topic_id}/articles/{article_id}")
async def delete_topic_article(topic_id: int, article_id: int, db: Session = Depends(get_db)):
    """Remove a single article from a topic."""
    article = db.query(TopicArticle).filter(
        TopicArticle.id == article_id, TopicArticle.topic_id == topic_id
    ).first()
    if not article:
        return {"error": "Article not found"}
    db.delete(article)
    db.commit()
    return {"success": True}


# --- Manual Search & Import ---

_CROSS_PRODUCT_LIMIT = 50   # pairs ≤ this → full cross-product (parallel)
_PARALLEL_CONCURRENCY = 5   # max simultaneous Google News requests


async def _multi_query_search(
    keywords: list[str],
    hours_back: int,
    max_per_query: int = 20,
) -> tuple[list[dict], str]:
    """Search Google News with an automatic strategy based on keyword structure.

    1 group  → 1 query (unchanged).
    2 groups → full cross-product if pairs ≤ CROSS_PRODUCT_LIMIT, else anchor.
    3+ groups → anchor on smallest group.

    All multi-query variants run **in parallel** (asyncio.gather + semaphore)
    so total wall-clock time ≈ max(single_request_time) regardless of query count.

    Returns (deduplicated_articles, description_string).
    """
    import asyncio
    from backend.services.google_news import search_google_news

    groups = _parse_keyword_groups(keywords)

    # --- 1 group: individual query per keyword for full recall ---
    if len(groups) <= 1:
        if len(keywords) <= 1:
            gn_query = _build_topic_gn_query(keywords)
            articles = await search_google_news(query=gn_query, hours_back=hours_back, max_results=max_per_query)
            return articles, f"1 次查詢：{gn_query[:60]}"
        # Multiple simple keywords → one query per keyword (parallel)
        kw_queries = keywords[:_CROSS_PRODUCT_LIMIT]
        semaphore = asyncio.Semaphore(_PARALLEL_CONCURRENCY)

        async def _fetch_simple_kw(kw: str) -> list[dict]:
            async with semaphore:
                try:
                    return await search_google_news(query=kw, hours_back=hours_back, max_results=max_per_query)
                except Exception:
                    return []

        batch_results = await asyncio.gather(*[_fetch_simple_kw(kw) for kw in kw_queries])
        seen_urls: set[str] = set()
        all_articles: list[dict] = []
        for batch in batch_results:
            for a in batch:
                url = a.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(a)
        return all_articles, f"逐詞查詢 {len(kw_queries)} 次（共 {len(keywords)} 個關鍵字），{len(all_articles)} 篇候選"

    # --- Build query list ---
    if len(groups) == 2:
        pairs = [(a, b) for a in groups[0] for b in groups[1]]
        if len(pairs) <= _CROSS_PRODUCT_LIMIT:
            # Full cross-product: "Basel" "台灣", "Basel" "美國", ...
            queries = [f'"{a}" "{b}"' for a, b in pairs]
            mode = f"交叉積 {len(queries)} 次查詢（{groups[0][0]} × {groups[1][0]}…）"
        else:
            # Too many pairs: anchor on smallest group
            min_gi = 0 if len(groups[0]) <= len(groups[1]) else 1
            anchor_terms = groups[min_gi]
            other_terms = [t for g in groups if g is not groups[min_gi] for t in g]
            rest = " OR ".join(f'"{t}"' for t in other_terms)
            queries = [f'"{t}" ({rest})' for t in anchor_terms]
            mode = f"錨點 {len(queries)} 次查詢（{len(pairs)} 組合超過上限 {_CROSS_PRODUCT_LIMIT}）"
    else:
        # 3+ groups: anchor on smallest group
        min_gi = min(range(len(groups)), key=lambda i: len(groups[i]))
        anchor_terms = groups[min_gi]
        other_terms = [t for i, g in enumerate(groups) if i != min_gi for t in g]
        rest = " OR ".join(f'"{t}"' for t in other_terms)
        queries = [f'"{t}" ({rest})' for t in anchor_terms]
        mode = f"錨點 {len(queries)} 次查詢（{len(groups)} 組關鍵字）"

    # --- Parallel execution ---
    semaphore = asyncio.Semaphore(_PARALLEL_CONCURRENCY)

    async def _fetch(q: str) -> list[dict]:
        async with semaphore:
            try:
                return await search_google_news(query=q, hours_back=hours_back, max_results=max_per_query)
            except Exception:
                return []

    batch_results = await asyncio.gather(*[_fetch(q) for q in queries])

    seen_urls: set[str] = set()
    all_articles: list[dict] = []
    for batch in batch_results:
        for a in batch:
            url = a.get("source_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_articles.append(a)

    desc = f"{mode}，{len(all_articles)} 篇候選"
    return all_articles, desc


@router.post("/{topic_id}/search")
async def search_and_import(topic_id: int, req: SearchImportRequest, db: Session = Depends(get_db)):
    """Search Google News with topic keywords and import new articles.

    Multi-group (AND) keywords search once per anchor term for higher recall,
    then filter locally to enforce full AND logic.
    """
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {"error": "Topic not found"}

    keywords = json.loads(topic.keywords) if topic.keywords else []
    if not keywords:
        return {"error": "此主題尚未設定關鍵字", "imported": 0}

    articles, query_desc = await _multi_query_search(keywords, hours_back=req.hours_back)

    imported = 0
    seen_urls: set[str] = set()
    for a in articles:
        url = a.get("source_url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        # 與雷達自動歸類用同一套比對（條目間 OR、條目內 AND 群組 + NOT + 英文詞邊界）
        text = topic_match.article_text(a)
        if not topic_match.topic_matches(keywords, text):
            continue
        if db.query(TopicArticle).filter_by(topic_id=topic_id, source_url=url).first():
            continue
        db.add(TopicArticle(
            topic_id=topic_id,
            title=a.get("title", ""),
            content=a.get("content", ""),
            source=a.get("source", ""),
            source_url=url,
            published_at=_parse_dt(a.get("published_at")),
            add_source="manual",
            matched_keyword=topic_match.matched_keyword(keywords, text) or None,
        ))
        imported += 1

    db.commit()
    return {"imported": imported, "query_sent": query_desc}


def _parse_keyword_groups(keywords: list[str]) -> list[list[str]]:
    """Parse keyword list into AND-groups of OR-terms.

    Grouped:  ["(A OR B)", "(C OR D)"]  or  ['("A" OR "B") ("C" OR "D")']
              → [[A,B],[C,D]]  — ALL groups must match (AND), any term within (OR)
    Simple:   ["A", "B", "C"]
              → [[A,B,C]]  — any term matches (OR)
    """
    import re
    full = " ".join(keywords)
    raw_groups = re.findall(r"\(([^)]+)\)", full)
    if raw_groups:
        groups = []
        for raw in raw_groups:
            terms = [t.strip().strip("\"'") for t in re.split(r"\bOR\b", raw, flags=re.IGNORECASE)]
            terms = [t for t in terms if t]
            if terms:
                groups.append(terms)
        return groups or [keywords]
    return [keywords]


def _build_topic_gn_query(keywords: list[str]) -> str:
    """Build a Google News RSS query string from topic keywords.

    Boolean syntax (contains parentheses) → passed through as-is.
    Simple terms → joined with OR.
    """
    import re
    full = " ".join(keywords)
    if re.search(r"\(", full):
        return full
    return " OR ".join(keywords)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
