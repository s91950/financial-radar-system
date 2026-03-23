"""Router for Module 3: News Database."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import Article, get_db

router = APIRouter()


class ArticleUpdate(BaseModel):
    is_saved: bool | None = None
    user_notes: str | None = None
    tags: list[str] | None = None


class ManualFetchRequest(BaseModel):
    query: str | None = None
    hours_back: int = 24


class SaveSelectedRequest(BaseModel):
    articles: list[dict]


@router.get("/articles")
async def get_articles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    saved_only: bool = False,
    category: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    """Get articles from the news database."""
    query = db.query(Article).order_by(Article.fetched_at.desc())

    if saved_only:
        query = query.filter(Article.is_saved == True)
    if category:
        query = query.filter(Article.category == category)
    if search:
        query = query.filter(
            (Article.title.contains(search)) | (Article.content.contains(search))
        )

    total = query.count()
    articles = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "articles": [_article_to_dict(a) for a in articles],
    }


@router.get("/articles/{article_id}")
async def get_article(article_id: int, db: Session = Depends(get_db)):
    """Get a single article by ID."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        return {"error": "Article not found"}
    return _article_to_dict(article)


@router.put("/articles/{article_id}")
async def update_article(
    article_id: int,
    update: ArticleUpdate,
    db: Session = Depends(get_db),
):
    """Update article properties (save/unsave, notes, tags)."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        return {"error": "Article not found"}

    if update.is_saved is not None:
        article.is_saved = update.is_saved
    if update.user_notes is not None:
        article.user_notes = update.user_notes
    if update.tags is not None:
        article.tags = json.dumps(update.tags, ensure_ascii=False)

    db.commit()
    db.refresh(article)
    return _article_to_dict(article)


@router.delete("/articles/{article_id}")
async def delete_article(article_id: int, db: Session = Depends(get_db)):
    """Delete an article from the database."""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        return {"error": "Article not found"}
    db.delete(article)
    db.commit()
    return {"success": True}


@router.post("/fetch")
async def manual_fetch(req: ManualFetchRequest, db: Session = Depends(get_db)):
    """Fetch news and return preview (does NOT auto-save).

    Returns fetched articles with already_in_db flag for user to select.
    """
    from backend.database import MonitorSource
    from backend.services import rss_feed
    from backend.services.google_news import search_google_news

    articles_data = []

    if req.query:
        news_results = await search_google_news(query=req.query, hours_back=req.hours_back)
        articles_data.extend(news_results)
    else:
        # Fetch general financial news
        for topic in ["金融市場", "台股", "經濟"]:
            news_results = await search_google_news(query=topic, hours_back=req.hours_back, max_results=10)
            articles_data.extend(news_results)

        sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "rss",
        ).all()
        feeds = [
            {
                "name": s.name,
                "url": s.url,
                "keywords": json.loads(s.keywords) if s.keywords else [],
            }
            for s in sources
        ]
        if feeds:
            for feed_info in feeds:
                rss_articles = await rss_feed.fetch_rss_feed(feed_info["url"], req.hours_back)
                articles_data.extend(rss_articles)

    # Mark which are already in DB (dedup by URL)
    preview = []
    seen_urls = set()
    for data in articles_data:
        url = data.get("source_url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        already_in_db = False
        if url:
            already_in_db = db.query(Article).filter(Article.source_url == url).first() is not None

        preview.append({
            **data,
            "already_in_db": already_in_db,
        })

    return {
        "fetched": len(preview),
        "preview": preview,
        "query": req.query,
    }


@router.post("/save-selected")
async def save_selected(req: SaveSelectedRequest, db: Session = Depends(get_db)):
    """Save user-selected articles to SQLite + Google Sheets."""
    from backend.services.google_sheets import append_news

    saved_count = 0
    saved_articles = []

    for data in req.articles:
        url = data.get("source_url", "")
        if url and db.query(Article).filter(Article.source_url == url).first():
            continue

        article = Article(
            title=data.get("title", ""),
            content=data.get("content", ""),
            source=data.get("source", ""),
            source_url=url,
            published_at=_parse_datetime(data.get("published_at")),
            category=data.get("category", "news"),
        )
        db.add(article)
        saved_count += 1
        saved_articles.append(data)

    db.commit()

    # Also append to Google Sheets news archive
    sheets_count = await append_news(saved_articles)

    return {
        "saved": saved_count,
        "sheets_saved": sheets_count,
    }


@router.get("/sentiment")
async def get_sentiment(db: Session = Depends(get_db)):
    """Get market heat/sentiment indicators based on today's articles."""
    from backend.services.sentiment import analyze_sentiment

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    articles = db.query(Article).filter(Article.fetched_at >= today_start).all()

    articles_data = [
        {"title": a.title, "content": a.content, "category": a.category}
        for a in articles
    ]

    sentiment = analyze_sentiment(articles_data)
    return {
        "date": today_start.strftime("%Y-%m-%d"),
        "total_articles": len(articles),
        "categories": sentiment,
    }


@router.get("/export")
async def export_articles(
    format: str = Query("json", pattern="^(json|csv)$"),
    saved_only: bool = True,
    db: Session = Depends(get_db),
):
    """Export saved articles as JSON or CSV."""
    query = db.query(Article).order_by(Article.fetched_at.desc())
    if saved_only:
        query = query.filter(Article.is_saved == True)
    articles = query.all()

    if format == "csv":
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Title", "Source", "URL", "Published", "Category", "Tags", "Notes"])
        for a in articles:
            writer.writerow([
                a.id, a.title, a.source, a.source_url,
                a.published_at, a.category, a.tags, a.user_notes,
            ])
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=news_export.csv"},
        )

    return [_article_to_dict(a) for a in articles]


@router.get("/categories")
async def get_categories(db: Session = Depends(get_db)):
    """Get all unique article categories."""
    categories = db.query(Article.category).distinct().all()
    return [c[0] for c in categories if c[0]]


def _article_to_dict(article: Article) -> dict:
    tags = []
    if article.tags:
        try:
            tags = json.loads(article.tags)
        except (json.JSONDecodeError, TypeError):
            tags = []

    return {
        "id": article.id,
        "title": article.title,
        "content": article.content,
        "summary": article.summary,
        "source": article.source,
        "source_url": article.source_url,
        "category": article.category,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
        "is_saved": article.is_saved,
        "user_notes": article.user_notes,
        "tags": tags,
    }


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
