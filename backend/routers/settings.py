"""Router for system settings management."""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import MonitorSource, NotificationSetting, get_db

router = APIRouter()


# --- Monitor Sources ---

class SourceCreate(BaseModel):
    name: str
    type: str  # 'rss' | 'website' | 'social' | 'newsapi'
    url: str
    keywords: list[str] = []


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None


@router.get("/sources")
async def get_sources(db: Session = Depends(get_db)):
    """Get all monitor sources."""
    sources = db.query(MonitorSource).all()
    return [_source_to_dict(s) for s in sources]


@router.post("/sources")
async def create_source(source: SourceCreate, db: Session = Depends(get_db)):
    """Add a new monitor source."""
    item = MonitorSource(
        name=source.name,
        type=source.type,
        url=source.url,
        keywords=json.dumps(source.keywords, ensure_ascii=False),
        is_active=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _source_to_dict(item)


@router.put("/sources/{source_id}")
async def update_source(
    source_id: int,
    update: SourceUpdate,
    db: Session = Depends(get_db),
):
    """Update a monitor source."""
    source = db.query(MonitorSource).filter(MonitorSource.id == source_id).first()
    if not source:
        return {"error": "Source not found"}

    if update.name is not None:
        source.name = update.name
    if update.url is not None:
        source.url = update.url
    if update.keywords is not None:
        source.keywords = json.dumps(update.keywords, ensure_ascii=False)
    if update.is_active is not None:
        source.is_active = update.is_active

    db.commit()
    return _source_to_dict(source)


@router.delete("/sources/{source_id}")
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    """Delete a monitor source."""
    source = db.query(MonitorSource).filter(MonitorSource.id == source_id).first()
    if not source:
        return {"error": "Source not found"}
    db.delete(source)
    db.commit()
    return {"success": True}


# --- Notification Settings ---

class NotificationUpdate(BaseModel):
    is_enabled: bool | None = None
    config: dict | None = None


@router.get("/notifications")
async def get_notification_settings(db: Session = Depends(get_db)):
    """Get all notification settings."""
    settings = db.query(NotificationSetting).all()
    return [_notification_to_dict(s) for s in settings]


@router.put("/notifications/{channel}")
async def update_notification_setting(
    channel: str,
    update: NotificationUpdate,
    db: Session = Depends(get_db),
):
    """Update notification settings for a channel."""
    setting = db.query(NotificationSetting).filter(
        NotificationSetting.channel == channel
    ).first()
    if not setting:
        return {"error": "Channel not found"}

    if update.is_enabled is not None:
        setting.is_enabled = update.is_enabled
    if update.config is not None:
        setting.config = json.dumps(update.config, ensure_ascii=False)

    db.commit()
    return _notification_to_dict(setting)


@router.post("/notifications/test/{channel}")
async def test_notification(channel: str, db: Session = Depends(get_db)):
    """Send a test notification through the specified channel."""
    from backend.services.notification import send_email, send_line_notify

    test_message = "🔔 這是金融偵測系統的測試通知。如果你看到這條訊息，表示通知設定正常運作！"

    if channel == "line":
        success = await send_line_notify(test_message)
        return {"success": success, "channel": "line"}
    elif channel == "email":
        success = await send_email(
            subject="[金融偵測系統] 測試通知",
            body=f"<p>{test_message}</p>",
        )
        return {"success": success, "channel": "email"}
    elif channel == "web":
        return {"success": True, "channel": "web", "message": "Web notifications are always available"}
    else:
        return {"error": f"Unknown channel: {channel}"}


# --- Google Sheets ---

@router.get("/google-sheets")
async def get_google_sheets_status():
    """Get Google Sheets connection status."""
    import os

    from backend.config import settings as cfg

    creds_exists = os.path.exists(cfg.GOOGLE_SHEETS_CREDENTIALS_FILE)
    sheet_id = cfg.GOOGLE_SHEETS_SPREADSHEET_ID
    configured = creds_exists and sheet_id not in ("", "your_spreadsheet_id_here")

    return {
        "configured": configured,
        "credentials_file": cfg.GOOGLE_SHEETS_CREDENTIALS_FILE,
        "credentials_exists": creds_exists,
        "spreadsheet_id": sheet_id[:10] + "..." if len(sheet_id) > 10 else sheet_id,
        "position_sheet": cfg.GOOGLE_SHEETS_POSITION_SHEET,
        "news_sheet": cfg.GOOGLE_SHEETS_NEWS_SHEET,
    }


@router.post("/google-sheets/test")
async def test_google_sheets():
    """Test Google Sheets connection."""
    from backend.services.google_sheets import get_positions, test_connection

    result = await test_connection()
    if result.get("success"):
        positions = await get_positions()
        result["position_count"] = len(positions)
    return result


def _source_to_dict(source: MonitorSource) -> dict:
    keywords = []
    if source.keywords:
        try:
            keywords = json.loads(source.keywords)
        except (json.JSONDecodeError, TypeError):
            keywords = []

    return {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "url": source.url,
        "keywords": keywords,
        "is_active": source.is_active,
    }


def _notification_to_dict(setting: NotificationSetting) -> dict:
    config = {}
    if setting.config:
        try:
            config = json.loads(setting.config)
        except (json.JSONDecodeError, TypeError):
            config = {}

    return {
        "id": setting.id,
        "channel": setting.channel,
        "is_enabled": setting.is_enabled,
        "config": config,
    }
