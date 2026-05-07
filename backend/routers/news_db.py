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
    source: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    fetched_after: str | None = Query(None, description="只回傳 fetched_at 晚於此時間的文章（ISO 8601，供 NLM 腳本使用）"),
    db: Session = Depends(get_db),
):
    """Get articles from the news database."""
    from datetime import datetime
    from sqlalchemy import not_
    query = db.query(Article).order_by(Article.fetched_at.desc())

    if saved_only:
        query = query.filter(Article.is_saved == True)
    if category:
        query = query.filter(Article.category == category)
    if source:
        if source == '__other__':
            from backend.database import MonitorSource
            configured_names = {
                r[0] for r in db.query(MonitorSource.name)
                .filter(MonitorSource.is_deleted == False)
                .all() if r[0]
            }
            query = query.filter(~Article.source.in_(configured_names))
        else:
            query = query.filter(Article.source == source)
    if keyword:
        query = query.filter(Article.matched_keyword.contains(keyword))
    if search:
        query = query.filter(
            (Article.title.contains(search)) | (Article.content.contains(search))
        )
    if severity == 'critical':
        # 優先使用掃描時存入的 severity 欄位（含 fixed_severity）；舊資料（severity=NULL）fallback 關鍵字比對
        from sqlalchemy import or_, not_
        query = query.filter(or_(
            Article.severity == 'critical',
            (Article.severity == None) & _kw_filter(_CRITICAL_KWS),
        ))
    elif severity == 'high':
        from sqlalchemy import or_, not_
        query = query.filter(or_(
            Article.severity == 'high',
            (Article.severity == None) & _kw_filter(_HIGH_KWS) & not_(_kw_filter(_CRITICAL_KWS)),
        ))
    elif severity == 'low':
        from sqlalchemy import or_, not_
        query = query.filter(or_(
            Article.severity == 'low',
            (Article.severity == None) & not_(_kw_filter(_CRITICAL_KWS)) & not_(_kw_filter(_HIGH_KWS)),
        ))
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
    if fetched_after:
        try:
            query = query.filter(Article.fetched_at >= datetime.fromisoformat(fetched_after.replace("Z", "+00:00")))
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


_PUNCT_TRIM_RE = None  # populated lazily

def _normalize_query_text(s: str) -> str:
    """文字正規化：用於查詢與被比對文字。
    - 全形→半形（標點與空白）
    - 移除所有空白
    - 小寫
    讓「美股收紅！」與「美股收紅!」、「台積 電」與「台積電」能對上。
    """
    import re, unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def _split_query_terms(query: str) -> list[str]:
    """拆分查詢字串：先做空白/全半形正規化，再切 ASCII/CJK 邊界，
    對長段中文額外產生 n-gram（4 字、6 字）做寬鬆比對。

    使用方式：呼叫端應對被比對文字也套用 `_normalize_query_text()`，
    然後檢查任一 term 是否為 substring（OR 邏輯）。
    """
    import re, unicodedata
    if not query:
        return []
    # 正規化但保留可分詞的空白資訊：先 NFKC，但暫不 strip 空白
    norm = unicodedata.normalize("NFKC", query)
    parts: list[str] = []
    for token in norm.split():
        # 切 ASCII↔CJK 邊界（含底線/破折號的英數視為一塊）
        sub = re.split(
            r'(?<=[A-Za-z0-9])(?=[^\x00-\x7F])|(?<=[^\x00-\x7F])(?=[A-Za-z0-9])',
            token,
        )
        for s in sub:
            s = s.strip().lower()
            if len(s) < 2:
                continue
            parts.append(s)
            # 長中文段：補 n-gram 讓「貼整段標題」也能用部分文字命中
            if len(s) >= 6 and not re.match(r'^[\x00-\x7F]+$', s):
                # 4-gram 取首尾與中段，避免完全 O(n²) 爆量
                grams = {s[:4], s[-4:]}
                if len(s) >= 8:
                    grams.add(s[len(s)//2 - 2: len(s)//2 + 2])
                # 6-gram 取首尾（給更長的標題段使用）
                if len(s) >= 12:
                    grams.add(s[:6])
                    grams.add(s[-6:])
                parts.extend(g for g in grams if len(g) >= 4)
    # 去重保序
    seen = set()
    out = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out if out else [_normalize_query_text(query)]


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

    def _query_match(article: dict, terms: list[str]) -> bool:
        """以正規化文字 + OR 子字串比對；任一 term 命中即過。"""
        text = _normalize_query_text(
            (article.get("title", "") or "") + " " + (article.get("content", "") or "")
        )
        return any(t in text for t in terms)

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
        # sources_only 模式：RSS + social + website + MOPS（與雷達掃描來源範圍一致）
        # 1) RSS / social：兩者皆為 feedparser 流程
        rss_sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.is_deleted == False,
            MonitorSource.type.in_(["rss", "social"]),
        ).all()
        feeds = [
            {"name": s.name, "url": s.url, "keywords": json.loads(s.keywords) if s.keywords else [],
             "fetch_all": bool(getattr(s, "fetch_all", False))}
            for s in rss_sources
        ]
        if feeds:
            if req.query:
                # 使用者有輸入關鍵字時，搜尋原始（未經來源關鍵字過濾）的所有文章，
                # 避免因來源設定了不同的關鍵字而漏掉使用者想找的文章。
                terms = _split_query_terms(req.query)
                _, raw_articles = await rss_feed.fetch_multiple_feeds(feeds, hours_back=req.hours_back, return_raw=True)
                articles_data = [a for a in raw_articles if _query_match(a, terms)]
            else:
                rss_results, _ = await rss_feed.fetch_multiple_feeds(
                    feeds, hours_back=req.hours_back, global_topics=all_topics, return_raw=True
                )
                articles_data = rss_results

        # 2) website 類型來源（含鉅亨網 JSON API、Fed、FSC、Caixin、太報、UDN…）
        ws_sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.is_deleted == False,
            MonitorSource.type == "website",
        ).all()
        for ws in ws_sources:
            try:
                from backend.scheduler.jobs import _fetch_website_source
                ws_articles = await _fetch_website_source(ws.url, req.hours_back)
                # 用 MonitorSource.name 覆蓋爬蟲寫死的 source 名稱（與雷達一致）
                for _a in ws_articles:
                    _a["source"] = ws.name
                ws_kws = json.loads(ws.keywords) if ws.keywords else []
                if req.query:
                    terms = _split_query_terms(req.query)
                    ws_articles = [a for a in ws_articles if _query_match(a, terms)]
                elif ws_kws and not getattr(ws, "fetch_all", False):
                    from backend.services.rss_feed import _filter_by_keywords
                    ws_articles = _filter_by_keywords(ws_articles, ws_kws)
                elif all_topics and not getattr(ws, "fetch_all", False):
                    from backend.services.rss_feed import _filter_by_topic_strings
                    ws_articles = _filter_by_topic_strings(ws_articles, all_topics)
                articles_data.extend(ws_articles)
            except Exception:
                pass

        # 3) MOPS 公開資訊觀測站（與雷達一致，僅取啟用中的 mops 來源）
        mops_source = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.is_deleted == False,
            MonitorSource.type == "mops",
        ).first()
        if mops_source:
            try:
                from backend.services.mops_scraper import fetch_mops_material_news
                mops_articles = await fetch_mops_material_news(hours_back=req.hours_back)
                for _a in mops_articles:
                    _a["source"] = mops_source.name
                mops_kws = json.loads(mops_source.keywords) if mops_source.keywords else []
                if req.query:
                    terms = _split_query_terms(req.query)
                    mops_articles = [a for a in mops_articles if _query_match(a, terms)]
                elif mops_kws and not getattr(mops_source, "fetch_all", False):
                    from backend.services.rss_feed import _filter_by_keywords
                    mops_articles = _filter_by_keywords(mops_articles, mops_kws)
                elif all_topics and not getattr(mops_source, "fetch_all", False):
                    from backend.services.rss_feed import _filter_by_topic_strings
                    mops_articles = _filter_by_topic_strings(mops_articles, all_topics)
                articles_data.extend(mops_articles)
            except Exception:
                pass

    # 全域排除關鍵字過濾（與雷達掃描邏輯一致，包含 fetch_all 來源）
    from backend.database import SystemConfig
    _excl_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_exclusion_keywords").first()
    try:
        _exclusion_kws = json.loads(_excl_cfg.value) if _excl_cfg else []
    except Exception:
        _exclusion_kws = []
    if _exclusion_kws:
        from backend.services.rss_feed import _term_in_text as _rss_term_in_text
        articles_data = [
            a for a in articles_data
            if not any(
                _rss_term_in_text(kw, f"{a.get('title', '')} {a.get('content', '')}".lower())
                for kw in _exclusion_kws
            )
        ]

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

    # Push to Google Sheets via GAS (instant); pullFromVM() every 30min is backup
    sheets_count = 0
    if saved_articles:
        from backend.services.google_sheets import append_news_via_gas
        gas_ok = await append_news_via_gas(saved_articles)
        if gas_ok:
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


@router.get("/sources")
async def get_sources(db: Session = Depends(get_db)):
    """Get article source names, grouped by configured MonitorSource; unconfigured → '其他'."""
    from sqlalchemy import func
    from backend.database import MonitorSource

    # 取得所有已設定的來源名稱
    configured_names = {
        r[0] for r in db.query(MonitorSource.name)
        .filter(MonitorSource.is_deleted == False)
        .all() if r[0]
    }

    rows = (
        db.query(Article.source, func.count(Article.id))
        .filter(Article.source != None, Article.source != "")
        .group_by(Article.source)
        .order_by(func.count(Article.id).desc())
        .all()
    )

    result = []
    other_count = 0
    for name, count in rows:
        if name in configured_names:
            result.append({"name": name, "count": count})
        else:
            other_count += count

    if other_count > 0:
        result.append({"name": "__other__", "count": other_count})

    return result


@router.get("/keywords")
async def get_keywords(db: Session = Depends(get_db)):
    """Get all unique matched_keyword values."""
    from sqlalchemy import func
    rows = (
        db.query(Article.matched_keyword, func.count(Article.id))
        .filter(Article.matched_keyword != None, Article.matched_keyword != "")
        .group_by(Article.matched_keyword)
        .order_by(func.count(Article.id).desc())
        .all()
    )
    return [{"keyword": r[0], "count": r[1]} for r in rows]


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
        "published_at": (article.published_at.isoformat() + "Z") if article.published_at else None,
        "fetched_at": (article.fetched_at.isoformat() + "Z") if article.fetched_at else None,
        "is_saved": article.is_saved,
        "user_notes": article.user_notes,
        "tags": tags,
        "matched_keyword": article.matched_keyword or None,
        "severity": article.severity or None,
    }


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, AttributeError):
        return None
