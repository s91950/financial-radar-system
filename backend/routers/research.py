"""研究報告 router — /api/research"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import MonitorSource, ResearchReport, get_db
from backend.services.research_feed import fetch_all_research_feeds

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Helpers ---

def _to_dict(r: ResearchReport) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "abstract": r.abstract or "",
        "authors": json.loads(r.authors) if r.authors else [],
        "source": r.source or "",
        "source_url": r.source_url or "",
        "pdf_url": r.pdf_url or "",
        "publication_date": r.publication_date.isoformat() if r.publication_date else None,
        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        "is_saved": r.is_saved or False,
        "tags": json.loads(r.tags) if r.tags else [],
        "user_notes": r.user_notes or "",
    }


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


# --- Endpoints ---

@router.get("/institutions")
def get_institutions(db: Session = Depends(get_db)):
    """回傳所有啟用的研究機構名稱清單。"""
    sources = (
        db.query(MonitorSource)
        .filter(MonitorSource.type == "research", MonitorSource.is_active == True)
        .all()
    )
    return [{"name": s.name, "url": s.url, "id": s.id} for s in sources]


@router.get("/reports")
def get_reports(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    institution: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    saved_only: bool = False,
    db: Session = Depends(get_db),
):
    """取得已儲存的研究報告（支援分頁、關鍵字、機構、日期篩選）。"""
    q = db.query(ResearchReport).order_by(ResearchReport.publication_date.desc().nullslast(),
                                           ResearchReport.fetched_at.desc())
    if saved_only:
        q = q.filter(ResearchReport.is_saved == True)
    if institution:
        q = q.filter(ResearchReport.source == institution)
    if search:
        like = f"%{search}%"
        q = q.filter(
            ResearchReport.title.ilike(like) | ResearchReport.abstract.ilike(like)
        )
    if date_from:
        dt = _parse_dt(date_from)
        if dt:
            q = q.filter(ResearchReport.publication_date >= dt)
    if date_to:
        dt = _parse_dt(date_to + "T23:59:59" if "T" not in date_to else date_to)
        if dt:
            q = q.filter(ResearchReport.publication_date <= dt)

    total = q.count()
    reports = q.offset(offset).limit(limit).all()
    return {"total": total, "reports": [_to_dict(r) for r in reports]}


class UpdateReportRequest(BaseModel):
    is_saved: Optional[bool] = None
    tags: Optional[list[str]] = None
    user_notes: Optional[str] = None


@router.put("/{report_id}")
def update_report(report_id: int, body: UpdateReportRequest, db: Session = Depends(get_db)):
    r = db.query(ResearchReport).filter(ResearchReport.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if body.is_saved is not None:
        r.is_saved = body.is_saved
    if body.tags is not None:
        r.tags = json.dumps(body.tags, ensure_ascii=False)
    if body.user_notes is not None:
        r.user_notes = body.user_notes
    db.commit()
    db.refresh(r)
    return _to_dict(r)


@router.delete("/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db)):
    r = db.query(ResearchReport).filter(ResearchReport.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


class FetchRequest(BaseModel):
    hours_back: int = 72
    institutions: Optional[list[str]] = None  # None = 全部
    date_from: Optional[str] = None  # YYYY-MM-DD，自選時間範圍
    date_to: Optional[str] = None    # YYYY-MM-DD


@router.post("/fetch")
async def manual_fetch(body: FetchRequest, db: Session = Depends(get_db)):
    """手動抓取研究報告（預覽，不自動儲存）。"""
    # 計算 hours_back（自選日期範圍時從 date_from 到現在）
    hours_back = body.hours_back
    if body.date_from:
        try:
            from_dt = datetime.fromisoformat(body.date_from)
            delta = datetime.utcnow() - from_dt
            hours_back = max(1, int(delta.total_seconds() / 3600) + 24)
        except Exception:
            pass

    q = db.query(MonitorSource).filter(
        MonitorSource.type == "research",
        MonitorSource.is_active == True,
    )
    if body.institutions:
        q = q.filter(MonitorSource.name.in_(body.institutions))
    sources = q.all()

    if not sources:
        return {"fetched": 0, "preview": []}

    feed_sources = [{"name": s.name, "url": s.url} for s in sources]
    reports = await fetch_all_research_feeds(feed_sources, hours_back=hours_back)

    # 如果有 date_to，過濾掉超出範圍的報告
    if body.date_to:
        try:
            to_dt = datetime.fromisoformat(body.date_to + "T23:59:59")
            filtered = []
            for r in reports:
                pub = r.get("publication_date")
                if pub:
                    try:
                        pub_dt = datetime.fromisoformat(pub)
                        if pub_dt <= to_dt:
                            filtered.append(r)
                    except Exception:
                        filtered.append(r)
                else:
                    filtered.append(r)
            reports = filtered
        except Exception:
            pass

    # Mark already-in-db
    preview = []
    for r in reports:
        url = r.get("source_url", "")
        already = bool(url and db.query(ResearchReport).filter(ResearchReport.source_url == url).first())
        preview.append({**r, "already_in_db": already})

    return {"fetched": len(preview), "preview": preview}


class SaveReportItem(BaseModel):
    title: str
    abstract: Optional[str] = None
    authors: Optional[str] = None   # JSON string or None
    source: Optional[str] = None
    source_url: Optional[str] = None
    pdf_url: Optional[str] = None
    publication_date: Optional[str] = None


class SaveSelectedRequest(BaseModel):
    reports: list[SaveReportItem]


@router.post("/save-selected")
def save_selected(body: SaveSelectedRequest, db: Session = Depends(get_db)):
    """儲存使用者勾選的研究報告。"""
    saved = 0
    for item in body.reports:
        url = item.source_url or ""
        if url and db.query(ResearchReport).filter(ResearchReport.source_url == url).first():
            continue
        report = ResearchReport(
            title=item.title,
            abstract=item.abstract,
            authors=item.authors,
            source=item.source,
            source_url=url,
            pdf_url=item.pdf_url or url,
            publication_date=_parse_dt(item.publication_date),
        )
        db.add(report)
        saved += 1
    db.commit()
    return {"saved": saved}
