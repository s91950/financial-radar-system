"""Router for 篩選前資料 (RawArticle).

Provides list / search / stats / delete endpoints for unfiltered articles
captured by the radar scan before any filtering steps.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.database import RawArticle, get_db
from backend.routers.news_db import _normalize_query_text, _split_query_terms

router = APIRouter()


def _row_to_dict(r: RawArticle) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "summary": r.summary,
        "source": r.source,
        "source_url": r.source_url,
        "source_type": r.source_type,
        "published_at": (r.published_at.isoformat() + "Z") if r.published_at else None,
        "fetched_at": (r.fetched_at.isoformat() + "Z") if r.fetched_at else None,
        "matched_keyword": r.matched_keyword,
        "filter_status": r.filter_status,
        "filter_reason": r.filter_reason,
    }


@router.get("/articles")
async def list_raw_articles(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    source: str | None = None,
    source_type: str | None = None,
    filter_status: str | None = Query(None, description="passed | not_passed | all（預設 all）"),
    hours_back: int | None = Query(None, ge=1, le=720, description="回溯小時數（None=全部 7 天）"),
    db: Session = Depends(get_db),
):
    """列出 raw_articles（篩選前資料）。

    - search: 對 title + summary 做 normalize + n-gram OR 比對（與 NewsDB 搜尋一致）
    - source: 來源名稱（精準比對）
    - source_type: rss | social | website | mops | gn
    - filter_status: passed（最終進雷達）/ not_passed（被篩掉）/ all
    - hours_back: 限定 fetched_at 視窗
    """
    q = db.query(RawArticle)

    if hours_back:
        cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        q = q.filter(RawArticle.fetched_at >= cutoff)

    if source:
        q = q.filter(RawArticle.source == source)

    if source_type:
        q = q.filter(RawArticle.source_type == source_type)

    if filter_status == "passed":
        q = q.filter(RawArticle.filter_status == "passed")
    elif filter_status == "not_passed":
        q = q.filter(or_(RawArticle.filter_status.is_(None), RawArticle.filter_status != "passed"))

    if search:
        terms = _split_query_terms(search)
        if terms:
            # SQLite LIKE 不支援我們做的 normalize（移除空白/全形→半形），
            # 所以策略：先用最短的 1-2 個 term 做粗篩（DB 端 LIKE），再在 Python 端做精確 normalize 比對。
            primary = sorted(terms, key=len)[0] if terms else ""
            if primary:
                like = f"%{primary}%"
                q = q.filter(or_(RawArticle.title.ilike(like), RawArticle.summary.ilike(like)))

    total = q.order_by(RawArticle.fetched_at.desc()).count()
    rows = q.order_by(RawArticle.fetched_at.desc()).offset(offset).limit(limit * 3 if search else limit).all()

    # Python 端二次篩選（normalize 比對）
    if search:
        terms = _split_query_terms(search)
        filtered = []
        for r in rows:
            text = _normalize_query_text((r.title or "") + " " + (r.summary or ""))
            if any(t in text for t in terms):
                filtered.append(r)
                if len(filtered) >= limit:
                    break
        rows = filtered
        # search 模式下 total 不準確（DB 粗篩過），用 len(rows) 表示「本頁實際命中數」
        return {
            "total": len(rows),
            "articles": [_row_to_dict(r) for r in rows],
            "search_note": "search 模式下 total 為當頁實際命中筆數",
        }

    return {
        "total": total,
        "articles": [_row_to_dict(r) for r in rows[:limit]],
    }


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """總覽：總筆數、按 source_type / source / filter_status 分組計數、磁碟用量估算。"""
    total = db.query(func.count(RawArticle.id)).scalar() or 0

    # 按 source_type
    by_type = dict(
        db.query(RawArticle.source_type, func.count(RawArticle.id))
        .group_by(RawArticle.source_type)
        .all()
    )

    # 按 source（取前 30 名）
    by_source = (
        db.query(RawArticle.source, func.count(RawArticle.id))
        .group_by(RawArticle.source)
        .order_by(func.count(RawArticle.id).desc())
        .limit(30)
        .all()
    )

    # passed vs not_passed
    passed = db.query(func.count(RawArticle.id)).filter(RawArticle.filter_status == "passed").scalar() or 0
    not_passed = total - passed

    # 最舊與最新時間戳
    oldest = db.query(func.min(RawArticle.fetched_at)).scalar()
    newest = db.query(func.max(RawArticle.fetched_at)).scalar()

    return {
        "total": total,
        "passed": passed,
        "not_passed": not_passed,
        "by_source_type": by_type,
        "by_source": [{"name": n or "(未知)", "count": c} for n, c in by_source],
        "oldest_fetched_at": (oldest.isoformat() + "Z") if oldest else None,
        "newest_fetched_at": (newest.isoformat() + "Z") if newest else None,
    }


@router.get("/sources")
async def list_sources(db: Session = Depends(get_db)):
    """列出 raw_articles 中出現過的所有來源（含計數），給前端做篩選下拉。"""
    rows = (
        db.query(RawArticle.source, func.count(RawArticle.id))
        .filter(RawArticle.source != None, RawArticle.source != "")
        .group_by(RawArticle.source)
        .order_by(func.count(RawArticle.id).desc())
        .all()
    )
    return [{"name": n, "count": c} for n, c in rows]


@router.delete("/articles/{article_id}")
async def delete_raw_article(article_id: int, db: Session = Depends(get_db)):
    """刪除單一筆 raw_article（手動清理用）。"""
    row = db.query(RawArticle).filter(RawArticle.id == article_id).first()
    if not row:
        return {"error": "not found"}
    db.delete(row)
    db.commit()
    return {"success": True}


@router.post("/cleanup")
async def manual_cleanup(
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """手動觸發清理：刪除 fetched_at 超過 days 天的 raw_articles。"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = db.query(RawArticle).filter(RawArticle.fetched_at < cutoff).delete()
    db.commit()
    return {"deleted": result, "cutoff": cutoff.isoformat() + "Z"}
