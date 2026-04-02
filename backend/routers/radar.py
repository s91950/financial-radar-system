"""Router for Module 1: Real-time Detection Radar."""

import json
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import Alert, MarketWatchItem, SignalCondition, get_db
from backend.services import market_data

router = APIRouter()

CATEGORY_LABELS = {
    "equity": {"label": "股市", "icon": "chart-bar"},
    "bond": {"label": "債市", "icon": "banknotes"},
    "currency": {"label": "匯市", "icon": "currency-dollar"},
    "commodity": {"label": "原物料", "icon": "fire"},
    "crypto": {"label": "加密貨幣", "icon": "bitcoin"},
    "volatility": {"label": "波動率", "icon": "bolt"},
}


class WatchlistCreateRequest(BaseModel):
    symbol: str
    name: str
    category: str = "equity"
    description: str | None = None
    threshold_upper: float | None = None
    threshold_lower: float | None = None
    sort_order: int = 0


class WatchlistUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    threshold_upper: float | None = None
    threshold_lower: float | None = None
    sort_order: int | None = None


class ConditionCreateRequest(BaseModel):
    name: str
    operator: str  # 'gt' | 'lt' | 'gte' | 'lte' | 'between'
    value: float
    value2: float | None = None
    signal: str  # 'positive' | 'neutral' | 'negative'
    message: str = ""
    is_active: bool = True
    priority: int = 0


class ConditionUpdateRequest(BaseModel):
    name: str | None = None
    operator: str | None = None
    value: float | None = None
    value2: float | None = None
    signal: str | None = None
    message: str | None = None
    is_active: bool | None = None
    priority: int | None = None


@router.get("/alerts")
async def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
    saved_only: bool = False,
    severity: str | None = None,
    db: Session = Depends(get_db),
):
    """Get recent alerts from the radar."""
    query = db.query(Alert).order_by(Alert.created_at.desc())
    if unread_only:
        query = query.filter(Alert.is_read == False)
    if saved_only:
        query = query.filter(Alert.is_saved == True)
    if severity:
        query = query.filter(Alert.severity == severity)
    alerts = query.limit(limit).all()
    return [_alert_to_dict(a) for a in alerts]


@router.get("/alerts/stats")
async def get_alert_stats(db: Session = Depends(get_db)):
    """Get alert statistics."""
    total = db.query(Alert).count()
    unread = db.query(Alert).filter(Alert.is_read == False).count()
    critical = db.query(Alert).filter(Alert.severity == "critical", Alert.is_read == False).count()
    return {"total": total, "unread": unread, "critical": critical}


@router.put("/alerts/{alert_id}/save")
async def toggle_alert_save(alert_id: int, db: Session = Depends(get_db)):
    """Toggle the saved state of an alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return {"error": "Alert not found"}
    alert.is_saved = not alert.is_saved
    db.commit()
    return {"success": True, "is_saved": alert.is_saved}


@router.put("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: int, db: Session = Depends(get_db)):
    """Mark an alert as read."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return {"error": "Alert not found"}
    alert.is_read = True
    db.commit()
    return {"success": True}


@router.put("/alerts/read-all")
async def mark_all_read(db: Session = Depends(get_db)):
    """Mark all alerts as read."""
    db.query(Alert).filter(Alert.is_read == False).update({"is_read": True})
    db.commit()
    return {"success": True}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    """Delete an alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return {"error": "Alert not found"}
    db.delete(alert)
    db.commit()
    return {"success": True}


@router.post("/alerts/{alert_id}/analyze")
async def analyze_alert(alert_id: int, db: Session = Depends(get_db)):
    """On-demand AI analysis for an alert (includes position exposure)."""
    from backend.services.ai_factory import get_ai_service
    from backend.services.exposure import format_exposure_summary, match_positions_to_news
    from backend.services.google_sheets import get_positions

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return {"error": "Alert not found"}

    if alert.analysis:
        return {"analysis": alert.analysis}

    # Build article-like dicts from alert content for exposure matching
    content_lines = (alert.content or "").split("\n")
    articles = [{"title": line, "content": ""} for line in content_lines if line.strip()]

    # Match positions
    positions = await get_positions()
    matched = match_positions_to_news(positions, articles) if positions else []
    exposure_summary = format_exposure_summary(matched) if matched else ""

    # Build context for AI
    exposure_context = f"\n\n可能影響的部位：\n{exposure_summary}" if exposure_summary else ""

    ai_service = get_ai_service()
    analysis = await ai_service.analyze_news(
        articles=[{"title": alert.title or "", "content": (alert.content or "") + exposure_context}],
    )

    if not analysis:
        return {"error": "AI 分析失敗（可能是 API 配額用完），請稍後再試"}

    alert.analysis = analysis
    db.commit()
    return {"analysis": analysis}


@router.get("/market")
async def get_market_data(db: Session = Depends(get_db)):
    """Get current market data for all watchlist items, grouped by category."""
    watchlist = db.query(MarketWatchItem).order_by(
        MarketWatchItem.category, MarketWatchItem.sort_order
    ).all()
    symbols = [w.symbol for w in watchlist]

    if not symbols:
        return {}

    quotes = await market_data.get_market_quotes(symbols)
    quotes_map = {q["symbol"]: q for q in quotes}

    # Update database and build grouped result
    grouped = defaultdict(list)
    for item in watchlist:
        quote = quotes_map.get(item.symbol, {})
        if quote.get("price"):
            item.current_value = quote["price"]
            item.change_percent = quote.get("change_percent", 0)
            item.last_updated = datetime.utcnow()

        cat = item.category or "equity"
        grouped[cat].append({
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "price": item.current_value,
            "change_percent": item.change_percent or 0,
            "signal_status": item.signal_status,
            "description": item.description,
            "category": cat,
            "threshold_upper": item.threshold_upper,
            "threshold_lower": item.threshold_lower,
            "sort_order": item.sort_order,
            "last_updated": (item.last_updated.isoformat() + "Z") if item.last_updated else None,
        })
    db.commit()
    return dict(grouped)


@router.get("/market/categories")
async def get_market_categories(db: Session = Depends(get_db)):
    """Get all available market categories with counts."""
    watchlist = db.query(MarketWatchItem).all()
    counts = defaultdict(int)
    for item in watchlist:
        counts[item.category or "equity"] += 1

    return [
        {
            "key": key,
            "label": CATEGORY_LABELS.get(key, {}).get("label", key),
            "icon": CATEGORY_LABELS.get(key, {}).get("icon", "chart-bar"),
            "count": counts.get(key, 0),
        }
        for key in CATEGORY_LABELS
        if counts.get(key, 0) > 0
    ]


@router.get("/market/history/{symbol}")
async def get_market_history(
    symbol: str,
    period: str = Query("5d", pattern="^(1d|5d|1mo|3mo|6mo|1y)$"),
    interval: str = Query("1h", pattern="^(5m|15m|30m|1h|1d)$"),
):
    """Get historical market data for a specific symbol."""
    data = await market_data.get_market_history(symbol, period, interval)
    return data


@router.get("/market/twse")
async def get_twse_data():
    """Get Taiwan Stock Exchange real-time data."""
    data = await market_data.get_twse_realtime()
    return data or {"error": "TWSE data unavailable"}


@router.post("/market/watchlist")
async def add_watchlist_item(req: WatchlistCreateRequest, db: Session = Depends(get_db)):
    """Add a new item to the market watchlist."""
    existing = db.query(MarketWatchItem).filter(MarketWatchItem.symbol == req.symbol).first()
    if existing:
        return {"error": "Symbol already in watchlist"}

    item = MarketWatchItem(
        symbol=req.symbol,
        name=req.name,
        category=req.category,
        description=req.description,
        threshold_upper=req.threshold_upper,
        threshold_lower=req.threshold_lower,
        sort_order=req.sort_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "symbol": item.symbol, "name": item.name, "category": item.category}


@router.put("/market/watchlist/{item_id}")
async def update_watchlist_item(
    item_id: int, req: WatchlistUpdateRequest, db: Session = Depends(get_db),
):
    """Update a watchlist item's properties."""
    item = db.query(MarketWatchItem).filter(MarketWatchItem.id == item_id).first()
    if not item:
        return {"error": "Item not found"}
    for field in ["name", "category", "description", "threshold_upper", "threshold_lower", "sort_order"]:
        val = getattr(req, field)
        if val is not None:
            setattr(item, field, val)
    db.commit()
    return {"success": True}


@router.delete("/market/watchlist/{item_id}")
async def delete_watchlist_item(item_id: int, db: Session = Depends(get_db)):
    """Remove an item from the watchlist (cascades to conditions)."""
    item = db.query(MarketWatchItem).filter(MarketWatchItem.id == item_id).first()
    if not item:
        return {"error": "Item not found"}
    db.delete(item)
    db.commit()
    return {"success": True}


# --- Signal Condition CRUD ---

@router.get("/market/watchlist/{item_id}/conditions")
async def get_conditions(item_id: int, db: Session = Depends(get_db)):
    """Get all signal conditions for a watchlist item."""
    conditions = (
        db.query(SignalCondition)
        .filter(SignalCondition.watchlist_id == item_id)
        .order_by(SignalCondition.priority)
        .all()
    )
    return [_condition_to_dict(c) for c in conditions]


@router.post("/market/watchlist/{item_id}/conditions")
async def create_condition(
    item_id: int, req: ConditionCreateRequest, db: Session = Depends(get_db),
):
    """Add a signal condition to a watchlist item."""
    item = db.query(MarketWatchItem).filter(MarketWatchItem.id == item_id).first()
    if not item:
        return {"error": "Watchlist item not found"}

    cond = SignalCondition(
        watchlist_id=item_id,
        name=req.name,
        operator=req.operator,
        value=req.value,
        value2=req.value2,
        signal=req.signal,
        message=req.message,
        is_active=req.is_active,
        priority=req.priority,
    )
    db.add(cond)
    db.commit()
    db.refresh(cond)
    return _condition_to_dict(cond)


@router.put("/market/conditions/{cond_id}")
async def update_condition(
    cond_id: int, req: ConditionUpdateRequest, db: Session = Depends(get_db),
):
    """Update a signal condition."""
    cond = db.query(SignalCondition).filter(SignalCondition.id == cond_id).first()
    if not cond:
        return {"error": "Condition not found"}
    for field in ["name", "operator", "value", "value2", "signal", "message", "is_active", "priority"]:
        val = getattr(req, field)
        if val is not None:
            setattr(cond, field, val)
    db.commit()
    return _condition_to_dict(cond)


@router.delete("/market/conditions/{cond_id}")
async def delete_condition(cond_id: int, db: Session = Depends(get_db)):
    """Delete a signal condition."""
    cond = db.query(SignalCondition).filter(SignalCondition.id == cond_id).first()
    if not cond:
        return {"error": "Condition not found"}
    db.delete(cond)
    db.commit()
    return {"success": True}


def _condition_to_dict(cond: SignalCondition) -> dict:
    return {
        "id": cond.id,
        "watchlist_id": cond.watchlist_id,
        "name": cond.name,
        "operator": cond.operator,
        "value": cond.value,
        "value2": cond.value2,
        "signal": cond.signal,
        "message": cond.message,
        "is_active": cond.is_active,
        "priority": cond.priority,
    }


@router.post("/scan")
async def manual_scan(background_tasks: BackgroundTasks):
    """Manually trigger a radar scan immediately (bypasses cross-process lock)."""
    from backend.scheduler.jobs import radar_scan
    background_tasks.add_task(radar_scan, True)
    return {"message": "雷達掃描已啟動"}


def _alert_to_dict(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "type": alert.type,
        "title": alert.title,
        "content": alert.content,
        "analysis": alert.analysis,
        "severity": alert.severity,
        "source": alert.source,
        "source_url": alert.source_url,
        "exposure_summary": alert.exposure_summary,
        "source_urls": json.loads(alert.source_urls) if alert.source_urls else [],
        "created_at": (alert.created_at.isoformat() + "Z") if alert.created_at else None,
        "is_read": alert.is_read,
        "is_saved": alert.is_saved or False,
    }
