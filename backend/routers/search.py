"""Router for Module 2: Topic Search.

Uses three free sources (no API key needed):
1. Google News RSS — realtime, supports Chinese
2. Local SQLite DB — search already-fetched articles
3. Configured RSS feeds — from MonitorSource table
"""

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database import Article, MonitorSource, get_db
from backend.services import claude_ai, rss_feed
from backend.services.exposure import format_exposure_summary, match_positions_to_news
from backend.services.google_news import search_google_news
from backend.services.google_sheets import get_positions

logger = logging.getLogger(__name__)

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    context: str = ""
    hours_back: int = 72
    include_ai_analysis: bool = False  # Default OFF — user triggers on demand


class AnalyzeRequest(BaseModel):
    query: str
    context: str = ""
    articles: list[dict] = []
    exposure_summary: str = ""


def _search_local_db(db: Session, query: str, hours_back: int) -> list[dict]:
    """Search articles already stored in SQLite by keyword matching."""
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    keywords = [kw.strip() for kw in query.split() if kw.strip()]

    filters = []
    for kw in keywords:
        pattern = f"%{kw}%"
        filters.append(
            or_(
                Article.title.ilike(pattern),
                Article.content.ilike(pattern),
                Article.tags.ilike(pattern),
            )
        )

    articles = (
        db.query(Article)
        .filter(*filters)
        .filter(or_(Article.published_at >= cutoff, Article.published_at.is_(None)))
        .order_by(Article.published_at.desc())
        .limit(20)
        .all()
    )

    return [
        {
            "title": a.title,
            "content": (a.content or "")[:300],
            "source": a.source or "本地資料庫",
            "source_url": a.source_url or "",
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "category": a.category or "local",
        }
        for a in articles
    ]


@router.post("/topic")
async def search_topic(req: SearchRequest, db: Session = Depends(get_db)):
    """Search news from multiple free sources + match position exposure.

    Sources: Google News RSS, local DB, configured RSS feeds.
    AI analysis is triggered separately via POST /topic/analyze.
    """
    # 1. Run Google News + position fetch in parallel
    google_task = search_google_news(
        query=req.query,
        hours_back=req.hours_back,
    )
    positions_task = get_positions()

    google_results, positions = await asyncio.gather(google_task, positions_task)

    # 2. Search local DB (sync, fast)
    local_results = _search_local_db(db, req.query, req.hours_back)

    # 3. Merge & deduplicate (Google News first, then local)
    seen_urls = set()
    all_articles = []
    for article in google_results + local_results:
        url = article.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        all_articles.append(article)

    # Match position exposure
    matched = match_positions_to_news(positions, all_articles) if positions else []
    exposure_summary = format_exposure_summary(matched) if matched else ""

    # Collect source URLs
    source_urls = [a.get("source_url", "") for a in all_articles if a.get("source_url")]

    # Save new articles to database
    saved_count = 0
    for article_data in all_articles:
        src_url = article_data.get("source_url")
        if not src_url:
            continue
        existing = db.query(Article).filter(Article.source_url == src_url).first()
        if not existing:
            article = Article(
                title=article_data.get("title", ""),
                content=article_data.get("content", ""),
                source=article_data.get("source", ""),
                source_url=src_url,
                published_at=_parse_datetime(article_data.get("published_at")),
                category=article_data.get("category", "search"),
                tags=f'["{req.query}"]',
            )
            db.add(article)
            saved_count += 1
    db.commit()

    result = {
        "query": req.query,
        "timestamp": datetime.utcnow().isoformat(),
        "news_articles": all_articles,
        "source_urls": source_urls[:10],
        "exposure_summary": exposure_summary,
        "matched_positions": [
            {
                "symbol": m["position"].get("symbol", ""),
                "name": m["position"].get("name", ""),
                "quantity": m["position"].get("quantity"),
                "avg_cost": m["position"].get("avg_cost"),
                "category": m["position"].get("category", ""),
                "relevance_score": m["relevance_score"],
                "matched_keywords": m["matched_keywords"],
            }
            for m in matched[:10]
        ],
        "articles_saved": saved_count,
    }

    # Optional: include AI analysis in same request
    if req.include_ai_analysis:
        claude_results = await claude_ai.search_and_analyze(
            query=req.query,
            context=req.context,
        )
        result["ai_analysis"] = claude_results.get("analysis", "")
        result["ai_sources"] = claude_results.get("sources", [])

    return result


@router.post("/topic/analyze")
async def analyze_topic(req: AnalyzeRequest):
    """Step 2: On-demand AI deep analysis with position exposure context."""
    # Build context with exposure info
    extra_context = req.context or ""
    if req.exposure_summary:
        extra_context += f"\n\n使用者持有的相關部位：\n{req.exposure_summary}"
    if req.articles:
        headlines = "\n".join(
            f"- [{a.get('source', '')}] {a.get('title', '')}"
            for a in req.articles[:10]
        )
        extra_context += f"\n\n相關新聞標題：\n{headlines}"

    claude_results = await claude_ai.search_and_analyze(
        query=req.query,
        context=extra_context,
    )

    return {
        "ai_analysis": claude_results.get("analysis", ""),
        "ai_sources": claude_results.get("sources", []),
    }


@router.get("/quick")
async def quick_search(
    q: str = Query(..., min_length=1),
    hours_back: int = Query(24, ge=1, le=168),
):
    """Quick search via Google News RSS — no API key needed."""
    results = await search_google_news(
        query=q,
        hours_back=hours_back,
    )
    return {"query": q, "results": results, "count": len(results)}


@router.get("/positions")
async def get_user_positions():
    """Get user positions from Google Sheets."""
    positions = await get_positions()
    return {"positions": positions, "count": len(positions)}


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
