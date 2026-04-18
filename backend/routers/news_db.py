"""Router for Module 3: News Database."""

import asyncio
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
    source_type: str = "sources_only"  # "sources_only" | "gn_only"


class SaveSelectedRequest(BaseModel):
    articles: list[dict]


_CRITICAL_KWS = ['崩盤', '暴跌', '危機', 'crash', 'crisis', 'emergency',
                 '戰爭', '制裁', '違約', '破產', '倒閉', '破產保護', '債務違約',
                 '勒索軟體', '網路攻擊', '資料外洩']
_HIGH_KWS = ['升息', '降息', '衰退', 'recession', 'inflation', '通膨',
             '獨家', '重訊', '重大訊息', '盈餘警告', '虧損擴大', '淨損',
             '信用評等', '調降', '縮編', '重組', '裁員', '出口禁令']


def _kw_filter(kws: list[str]):
    """Build OR filter: title or content contains any of the keywords."""
    from sqlalchemy import or_
    return or_(*[Article.title.ilike(f'%{kw}%') for kw in kws],
               *[Article.content.ilike(f'%{kw}%') for kw in kws])


@router.get("/articles")
async def get_articles(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    saved_only: bool = False,
    category: str | None = None,
    search: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_radar: bool = Query(False, description="是否包含雷達自動存檔（category=radar）的文章"),
    db: Session = Depends(get_db),
):
    """Get articles from the news database.

    預設排除雷達自動存檔（category='radar'）的文章，只顯示使用者手動儲存的文章。
    傳入 include_radar=true 可取得全部文章（NLM 腳本使用）。
    """
    from datetime import datetime
    from sqlalchemy import not_
    query = db.query(Article).order_by(Article.fetched_at.desc())

    # 預設排除雷達自動存檔（避免 GN 來源如 MEXC、MSN 混入新聞資料庫）
    if not include_radar:
        query = query.filter(Article.category != "radar")

    if saved_only:
        query = query.filter(Article.is_saved == True)
    if category:
        query = query.filter(Article.category == category)
    if search:
        query = query.filter(
            (Article.title.contains(search)) | (Article.content.contains(search))
        )
    if severity == 'critical':
        query = query.filter(_kw_filter(_CRITICAL_KWS))
    elif severity == 'high':
        query = query.filter(
            _kw_filter(_HIGH_KWS) & not_(_kw_filter(_CRITICAL_KWS))
        )
    elif severity == 'low':
        query = query.filter(
            not_(_kw_filter(_CRITICAL_KWS)) & not_(_kw_filter(_HIGH_KWS))
        )
    if date_from:
        try:
            query = query.filter(Article.published_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            from datetime import timedelta
            query = query.filter(Article.published_at < dt_to + timedelta(days=1))
        except ValueError:
            pass

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


def _load_radar_topics(db) -> list[str]:
    """從 SystemConfig + 主題追蹤載入完整關鍵字清單（與即時雷達一致）。"""
    from backend.database import SystemConfig, Topic

    tw_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_topics").first()
    us_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_topics_us").first()
    tw_topics: list[str] = json.loads(tw_cfg.value) if tw_cfg else ["金融", "股市", "經濟"]
    us_topics: list[str] = json.loads(us_cfg.value) if us_cfg else []

    topic_kws: list[str] = []
    for t in db.query(Topic).filter(Topic.is_active == True).all():
        try:
            topic_kws.extend(json.loads(t.keywords) if t.keywords else [])
        except Exception:
            pass

    return tw_topics + us_topics + topic_kws


async def _gn_fetch_topic(topic: str, hours_back: int) -> list[dict]:
    """GN 搜尋單一 topic，自動區分簡單/布林查詢（與雷達邏輯一致）。"""
    from backend.services.google_news import search_google_news
    try:
        if '(' in topic:
            from backend.scheduler.jobs import _multi_search_topic
            return await _multi_search_topic([topic], hours_back=hours_back, max_per_query=50)
        return await search_google_news(query=topic, hours_back=hours_back, max_results=50)
    except Exception:
        return []


def _split_query_terms(query: str) -> list[str]:
    """拆分查詢字串：空格分詞 + ASCII/CJK 邊界拆分，回傳 OR 比對詞組。

    "AI產業下一個瓶頸" → ["AI", "產業下一個瓶頸"]
    "Fed 升息"         → ["Fed", "升息"]
    "台積電"            → ["台積電"]
    """
    import re
    parts: list[str] = []
    for token in query.split():
        # Split at ASCII↔CJK boundary
        sub = re.split(r'(?<=[A-Za-z0-9])(?=[^\x00-\x7F])|(?<=[^\x00-\x7F])(?=[A-Za-z0-9])', token)
        parts.extend(s for s in sub if len(s) >= 2)
    return parts if parts else [query]


def _tag_matched_keywords(articles: list[dict], topics: list[str], query: str | None) -> None:
    """為每篇文章加上 matched_keyword（符合的第一個關鍵字）。In-place。"""
    if query:
        for a in articles:
            a.setdefault("matched_keyword", query)
        return
    from backend.services.rss_feed import _extract_display_kw
    for a in articles:
        if a.get("matched_keyword"):
            continue
        text = (a.get("title", "") + " " + a.get("content", "")).lower()
        for topic in topics:
            kw = _extract_display_kw(topic, text)
            if kw:
                a["matched_keyword"] = kw
                break


@router.post("/fetch")
async def manual_fetch(req: ManualFetchRequest, db: Session = Depends(get_db)):
    """Fetch news and return preview (does NOT auto-save).

    無自訂關鍵字時，使用與即時雷達相同的 radar_topics + 主題追蹤關鍵字。
    """
    from backend.database import MonitorSource
    from backend.services import rss_feed
    from backend.services.google_news import search_google_news

    articles_data = []
    all_topics = _load_radar_topics(db)

    if req.source_type == "gn_only":
        if req.query:
            news_results = await search_google_news(query=req.query, hours_back=req.hours_back, max_results=50)
            articles_data.extend(news_results)
        else:
            # 並行搜尋所有雷達主題（最多 30 個），布林查詢使用 _multi_search_topic
            semaphore = asyncio.Semaphore(5)
            async def _bounded(topic):
                async with semaphore:
                    return await _gn_fetch_topic(topic, req.hours_back)
            results = await asyncio.gather(*[_bounded(t) for t in all_topics[:30]])
            for r in results:
                articles_data.extend(r)
    else:
        # sources_only 模式：RSS + website（鉅亨網等）
        rss_sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "rss",
        ).all()
        feeds = [
            {"name": s.name, "url": s.url, "keywords": json.loads(s.keywords) if s.keywords else []}
            for s in rss_sources
        ]
        if feeds:
            if req.query:
                terms = _split_query_terms(req.query)
                rss_results, _ = await rss_feed.fetch_multiple_feeds(feeds, hours_back=req.hours_back, return_raw=True)
                articles_data = [
                    a for a in rss_results
                    if any(t.lower() in (a.get("title", "") + " " + a.get("content", "")).lower() for t in terms)
                ]
            else:
                rss_results, _ = await rss_feed.fetch_multiple_feeds(
                    feeds, hours_back=req.hours_back, global_topics=all_topics, return_raw=True
                )
                articles_data = rss_results

        # website 類型來源（含鉅亨網 JSON API）
        ws_sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "website",
        ).all()
        for ws in ws_sources:
            try:
                from backend.scheduler.jobs import _fetch_website_source
                ws_articles = await _fetch_website_source(ws.url, req.hours_back)
                ws_kws = json.loads(ws.keywords) if ws.keywords else []
                if req.query:
                    terms = _split_query_terms(req.query)
                    ws_articles = [a for a in ws_articles if any(t.lower() in (a.get("title","") + " " + a.get("content","")).lower() for t in terms)]
                elif ws_kws:
                    from backend.services.rss_feed import _filter_by_keywords
                    ws_articles = _filter_by_keywords(ws_articles, ws_kws)
                elif all_topics:
                    from backend.services.rss_feed import _filter_by_topic_strings
                    ws_articles = _filter_by_topic_strings(ws_articles, all_topics)
                articles_data.extend(ws_articles)
            except Exception:
                pass

    # 加上 matched_keyword 標籤
    _tag_matched_keywords(articles_data, all_topics, req.query)

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
    from backend.services.google_sheets import append_news, append_news_via_gas

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
            matched_keyword=data.get("matched_keyword") or None,
        )
        db.add(article)
        saved_count += 1
        saved_articles.append(data)

    db.commit()

    # Also append to Google Sheets (try GAS first, fallback to Service Account)
    sheets_count = 0
    if saved_articles:
        gas_ok = await append_news_via_gas(saved_articles)
        if not gas_ok:
            sheets_count = await append_news(saved_articles)
        else:
            sheets_count = len(saved_articles)

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
        "matched_keyword": article.matched_keyword or None,
    }


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
