"""Router for system settings management."""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import MonitorSource, NotificationSetting, SystemConfig, get_db

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


@router.get("/line-status")
async def get_line_status(db: Session = Depends(get_db)):
    """回傳 LINE Messaging API 設定狀態（不暴露實際 token 值）。"""
    from backend.config import settings as cfg
    token = cfg.LINE_CHANNEL_ACCESS_TOKEN
    min_sev = cfg.LINE_NOTIFY_MIN_SEVERITY
    token_ok = bool(token and token not in ("", "your_line_channel_access_token_here"))

    setting = db.query(NotificationSetting).filter(NotificationSetting.channel == "line").first()
    is_enabled = setting.is_enabled if setting else False
    if setting and setting.config:
        try:
            cfg_json = json.loads(setting.config)
            min_sev = cfg_json.get("min_severity") or min_sev
        except Exception:
            pass

    return {
        "token_configured": token_ok,
        "is_enabled": is_enabled,
        "ready": token_ok and is_enabled,
        "token_preview": (token[:6] + "…" + token[-4:]) if token_ok else None,
        "min_severity": min_sev,
    }


@router.post("/notifications/test/{channel}")
async def test_notification(channel: str, db: Session = Depends(get_db)):
    """Send a test notification through the specified channel."""
    from backend.services.notification import send_email, send_line_message

    test_message = "🔔 這是金融偵測系統的測試通知。如果你看到這條訊息，表示通知設定正常運作！"

    if channel in ("line", "line_messaging"):
        import httpx as _httpx
        from backend.config import settings as cfg
        token = cfg.LINE_CHANNEL_ACCESS_TOKEN
        target_id = cfg.LINE_TARGET_ID
        if not token or token in ("", "your_line_channel_access_token_here"):
            return {"success": False, "channel": channel, "error": "LINE_CHANNEL_ACCESS_TOKEN 未設定，請檢查 .env 檔案"}
        if not target_id or target_id in ("", "your_line_user_id_here", "your_line_target_id_here"):
            return {"success": False, "channel": channel, "error": "LINE_TARGET_ID 未設定，請在 .env 填入個人 User ID"}
        # 直接呼叫 push API，以便取得精確錯誤訊息
        try:
            async with _httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"to": target_id, "messages": [{"type": "text", "text": f"🔔 金融偵測系統 LINE 測試\n{test_message}"}]},
                )
            if resp.status_code == 200:
                return {"success": True, "channel": channel, "error": None}
            body = resp.json()
            api_msg = body.get("message", resp.text)
            if resp.status_code == 429:
                error = f"已達 LINE 每月訊息上限，請至 LINE Official Account Manager 升級方案（{api_msg}）"
            elif resp.status_code == 401:
                error = f"Channel Access Token 無效或已過期，請重新產生（{api_msg}）"
            elif resp.status_code == 400:
                error = f"LINE_TARGET_ID 格式錯誤，請確認為正確的 User ID（{api_msg}）"
            else:
                error = f"LINE API 錯誤 {resp.status_code}：{api_msg}"
            return {"success": False, "channel": channel, "error": error}
        except Exception as e:
            return {"success": False, "channel": channel, "error": f"連線失敗：{e}"}
    elif channel == "email":
        success = await send_email(
            subject="[金融偵測系統] 測試通知",
            body=f"<p>{test_message}</p>",
        )
        return {"success": success, "channel": "email"}
    elif channel == "discord":
        setting = db.query(NotificationSetting).filter(NotificationSetting.channel == "discord").first()
        if not setting:
            return {"success": False, "channel": "discord", "error": "Discord 管道尚未建立，請重新整理設定頁面"}
        try:
            cfg = json.loads(setting.config) if setting.config else {}
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        webhook_url = cfg.get("webhook_url", "")
        if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
            return {"success": False, "channel": "discord", "error": "Discord Webhook URL 未設定，請先在下方填入 Webhook URL"}
        from backend.services.notification import format_alert_discord, send_discord_webhook
        test_alert = {
            "title": "金融偵測系統 Discord 測試",
            "severity": "low",
            "content": "這是一則測試訊息，確認 Discord Webhook 通知正常運作。",
            "source_urls": [],
            "ai_structured": {"event_summary": "測試通知：如果你看到這則訊息，表示 Discord 通知設定正確！"},
        }
        success = await send_discord_webhook(webhook_url, test_alert)
        if success:
            return {"success": True, "channel": "discord", "error": None}
        return {"success": False, "channel": "discord", "error": "Discord Webhook 傳送失敗，請確認 Webhook URL 是否正確"}
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


# --- Radar Topics ---

_DEFAULT_RADAR_TOPICS = ["金融", "股市", "經濟"]


def _get_config(db: Session, key: str, default: str) -> str:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return row.value if row else default


def _set_config(db: Session, key: str, value: str):
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(SystemConfig(key=key, value=value))


@router.get("/radar-topics")
async def get_radar_topics(db: Session = Depends(get_db)):
    """Get Google News search topics and scan config for radar scan."""
    from backend.config import settings as cfg
    topics_raw = _get_config(db, "radar_topics", json.dumps(_DEFAULT_RADAR_TOPICS))
    hours_raw = _get_config(db, "radar_hours_back", "24")
    interval_raw = _get_config(db, "radar_interval_minutes", str(cfg.RADAR_INTERVAL_MINUTES))
    return {
        "topics": json.loads(topics_raw),
        "hours_back": int(hours_raw),
        "interval_minutes": int(interval_raw),
    }


class RadarTopicsUpdate(BaseModel):
    topics: list[str]
    hours_back: int = 24
    interval_minutes: int | None = None


@router.put("/radar-topics")
async def update_radar_topics(req: RadarTopicsUpdate, db: Session = Depends(get_db)):
    """Update Google News search topics, scan hours, and interval for radar scan."""
    from backend.config import settings as cfg
    _set_config(db, "radar_topics", json.dumps(req.topics, ensure_ascii=False))
    _set_config(db, "radar_hours_back", str(max(1, req.hours_back)))
    current_interval = int(_get_config(db, "radar_interval_minutes", str(cfg.RADAR_INTERVAL_MINUTES)))
    interval = req.interval_minutes
    from backend.scheduler.jobs import _flog
    _flog(f"[SETTINGS] interval req={interval} current={current_interval}")
    if interval is not None:
        interval = max(1, min(interval, 60))  # 限制 1~60 分鐘
        if interval != current_interval:
            # 只有在實際變更時才重新排程（避免每次儲存主題都重置倒數計時）
            _set_config(db, "radar_interval_minutes", str(interval))
            try:
                from backend.scheduler.jobs import scheduler
                if scheduler.running:
                    scheduler.reschedule_job(
                        "radar_scan", trigger="interval", minutes=interval
                    )
                    _flog(f"[SETTINGS] Rescheduled radar_scan to {interval} min OK")
                else:
                    _flog("[SETTINGS] Scheduler not running, skip reschedule")
            except Exception as e:
                _flog(f"[SETTINGS] reschedule FAILED: {e}")
                import logging
                logging.getLogger(__name__).warning(f"reschedule_job failed: {e}")
        else:
            _flog(f"[SETTINGS] interval unchanged ({interval}), skip reschedule")
    else:
        interval = current_interval
    db.commit()
    return {"topics": req.topics, "hours_back": req.hours_back, "interval_minutes": interval}


# --- Severity Keywords ---

_DEFAULT_CRITICAL_KW = ["崩盤","暴跌","危機","crash","crisis","emergency","戰爭","制裁","違約","破產","倒閉","破產保護","債務違約","勒索軟體","網路攻擊","資料外洩"]
_DEFAULT_HIGH_KW = ["升息","降息","衰退","recession","inflation","通膨","獨家","重訊","重大訊息","盈餘警告","虧損擴大","淨損","信用評等","調降","縮編","重組","裁員","出口禁令"]


def get_severity_keywords(db: Session) -> tuple[list[str], list[str]]:
    """Load severity keywords from DB (with hardcoded fallback). Importable by other modules."""
    try:
        crit = json.loads(_get_config(db, "severity_critical_kw", json.dumps(_DEFAULT_CRITICAL_KW)))
    except Exception:
        crit = list(_DEFAULT_CRITICAL_KW)
    try:
        high = json.loads(_get_config(db, "severity_high_kw", json.dumps(_DEFAULT_HIGH_KW)))
    except Exception:
        high = list(_DEFAULT_HIGH_KW)
    return crit, high


@router.get("/severity-keywords")
async def get_severity_keywords_api(db: Session = Depends(get_db)):
    """Get current severity keyword lists and their system defaults."""
    crit, high = get_severity_keywords(db)
    return {
        "critical": crit,
        "high": high,
        "default_critical": _DEFAULT_CRITICAL_KW,
        "default_high": _DEFAULT_HIGH_KW,
    }


class SeverityKeywordsRequest(BaseModel):
    critical: list[str]
    high: list[str]


@router.put("/severity-keywords")
async def update_severity_keywords_api(req: SeverityKeywordsRequest, db: Session = Depends(get_db)):
    """Update severity keyword lists. Takes effect on next radar scan / article load."""
    _set_config(db, "severity_critical_kw", json.dumps(req.critical, ensure_ascii=False))
    _set_config(db, "severity_high_kw", json.dumps(req.high, ensure_ascii=False))
    db.commit()
    return {"critical": req.critical, "high": req.high}


# --- AI Model Settings ---

class AIModelRequest(BaseModel):
    model: str  # "gemini" | "claude"


@router.get("/ai-model")
async def get_ai_model():
    """Get current AI engine setting."""
    from backend.config import settings
    return {
        "model": settings.DEFAULT_AI_MODEL,
        "gemini_model": settings.GEMINI_MODEL,
        "gemini_configured": bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY not in {"", "your_gemini_api_key_here"}),
        "claude_configured": bool(settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY not in {"", "your_anthropic_api_key_here"}),
    }


@router.put("/ai-model")
async def update_ai_model(req: AIModelRequest):
    """Switch AI engine at runtime (gemini | claude).

    Updates the in-memory settings. To persist across restarts, update .env file.
    """
    from backend.config import settings
    if req.model not in ("gemini", "claude"):
        return {"error": "model must be 'gemini' or 'claude'"}
    settings.DEFAULT_AI_MODEL = req.model
    return {"model": settings.DEFAULT_AI_MODEL, "message": f"已切換至 {req.model}"}
