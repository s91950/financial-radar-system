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
    fetch_all: bool = False


class SourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None  # 'rss' | 'website' | 'social' | 'mops' | 'person'
    url: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None
    fetch_all: bool | None = None
    fixed_severity: str | None = None  # '' = 清除（動態評估）; 'critical'|'high'|'low' = 強制覆寫


@router.get("/sources")
async def get_sources(db: Session = Depends(get_db)):
    """Get all monitor sources."""
    sources = db.query(MonitorSource).order_by(MonitorSource.sort_order, MonitorSource.id).all()
    return [_source_to_dict(s) for s in sources]


@router.put("/sources/reorder")
async def reorder_sources(order: list[int], db: Session = Depends(get_db)):
    """Bulk-update sort_order for all sources. `order` is a list of source IDs in desired order."""
    for i, source_id in enumerate(order):
        source = db.query(MonitorSource).filter(MonitorSource.id == source_id).first()
        if source:
            source.sort_order = i
    db.commit()
    return {"success": True}


@router.post("/sources")
async def create_source(source: SourceCreate, db: Session = Depends(get_db)):
    """Add a new monitor source."""
    item = MonitorSource(
        name=source.name,
        type=source.type,
        url=source.url,
        keywords=json.dumps(source.keywords, ensure_ascii=False),
        is_active=True,
        fetch_all=source.fetch_all,
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
    if update.type is not None:
        source.type = update.type
    if update.url is not None:
        source.url = update.url
    if update.keywords is not None:
        source.keywords = json.dumps(update.keywords, ensure_ascii=False)
    if update.is_active is not None:
        source.is_active = update.is_active
    if update.fetch_all is not None:
        source.fetch_all = update.fetch_all
    if update.fixed_severity is not None:
        source.fixed_severity = update.fixed_severity or None  # '' → None（清除）

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
        "fetch_all": bool(source.fetch_all),
        "sort_order": source.sort_order or 0,
        "fixed_severity": source.fixed_severity or None,
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
    topics_us_raw = _get_config(db, "radar_topics_us", "[]")
    hours_raw = _get_config(db, "radar_hours_back", "24")
    interval_raw = _get_config(db, "radar_interval_minutes", str(cfg.RADAR_INTERVAL_MINUTES))
    rss_only_raw = _get_config(db, "radar_rss_only", "false")
    excl_raw = _get_config(db, "radar_exclusion_keywords", "[]")
    return {
        "topics": json.loads(topics_raw),
        "topics_us": json.loads(topics_us_raw),
        "hours_back": int(hours_raw),
        "interval_minutes": int(interval_raw),
        "rss_only": rss_only_raw == "true",
        "exclusion_keywords": json.loads(excl_raw),
    }


class RadarTopicsUpdate(BaseModel):
    topics: list[str]
    topics_us: list[str] = []
    hours_back: int = 24
    interval_minutes: int | None = None
    rss_only: bool = False
    exclusion_keywords: list[str] = []


@router.put("/radar-topics")
async def update_radar_topics(req: RadarTopicsUpdate, db: Session = Depends(get_db)):
    """Update Google News search topics, scan hours, and interval for radar scan."""
    from backend.config import settings as cfg
    _set_config(db, "radar_topics", json.dumps(req.topics, ensure_ascii=False))
    _set_config(db, "radar_topics_us", json.dumps(req.topics_us, ensure_ascii=False))
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
    _set_config(db, "radar_rss_only", "true" if req.rss_only else "false")
    _set_config(db, "radar_exclusion_keywords", json.dumps(req.exclusion_keywords, ensure_ascii=False))
    db.commit()
    return {"topics": req.topics, "hours_back": req.hours_back, "interval_minutes": interval, "rss_only": req.rss_only}


# --- Radar Topic Categories ---

@router.get("/radar-topic-categories")
async def get_topic_categories(db: Session = Depends(get_db)):
    """取得關鍵字分類設定。格式：{分類名稱: [關鍵字...]}"""
    raw = _get_config(db, "radar_topic_categories", "{}")
    try:
        cats = json.loads(raw)
    except Exception:
        cats = {}
    return {"categories": cats}


class TopicCategoriesUpdate(BaseModel):
    categories: dict  # {分類名稱: [關鍵字...]}


@router.put("/radar-topic-categories")
async def update_topic_categories(req: TopicCategoriesUpdate, db: Session = Depends(get_db)):
    """更新關鍵字分類設定（不影響 radar_topics 本身）。"""
    _set_config(db, "radar_topic_categories", json.dumps(req.categories, ensure_ascii=False))
    db.commit()
    return {"categories": req.categories}


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


# --- Severity Boolean Rules ---
# 格式：[{"condition": "暴跌 AND 台股", "severity": "critical", "note": ""}]
# condition 使用與 Topic 相同的布林語法：空格=AND，括號=OR，AND/OR 關鍵字

_DEFAULT_SEVERITY_RULES: list[dict] = []


def get_severity_rules(db: Session) -> list[dict]:
    """Load severity boolean rules from DB. Importable by other modules."""
    try:
        return json.loads(_get_config(db, "severity_rules", "[]"))
    except Exception:
        return []


@router.get("/severity-rules")
async def get_severity_rules_api(db: Session = Depends(get_db)):
    return {"rules": get_severity_rules(db)}


class SeverityRulesRequest(BaseModel):
    rules: list[dict]  # [{"condition": str, "severity": str, "note": str}]


@router.put("/severity-rules")
async def update_severity_rules_api(req: SeverityRulesRequest, db: Session = Depends(get_db)):
    """更新布林嚴重度規則。規則優先於關鍵字列表，第一條符合即返回。"""
    # 基本驗證
    valid = []
    for r in req.rules:
        if not isinstance(r, dict):
            continue
        cond = str(r.get("condition", "")).strip()
        sev = str(r.get("severity", "")).strip()
        if cond and sev in ("critical", "high", "low"):
            valid.append({"condition": cond, "severity": sev, "note": str(r.get("note", ""))})
    _set_config(db, "severity_rules", json.dumps(valid, ensure_ascii=False))
    db.commit()
    return {"rules": valid}


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


# --- RSS Source Test ---

@router.post("/sources/{source_id}/test-rss")
async def test_rss_source(source_id: int, db: Session = Depends(get_db)):
    """測試 RSS 來源是否能正常抓取文章。回傳 feed 中的條目數與標題預覽。"""
    import feedparser
    import httpx

    source = db.query(MonitorSource).filter(MonitorSource.id == source_id).first()
    if not source:
        return {"success": False, "error": "來源不存在", "count": 0, "sample_titles": []}
    if source.type == "mops":
        try:
            from backend.services.mops_scraper import fetch_mops_material_news
            articles = await fetch_mops_material_news(hours_back=24)
            titles = [a["title"][:60] for a in articles[:5]]
            return {
                "success": True,
                "count": len(articles),
                "feed_title": "公開資訊觀測站重大訊息",
                "sample_titles": titles if titles else ["24 小時內無重大訊息"],
                "error": None,
            }
        except Exception as e:
            return {"success": False, "error": f"MOPS 爬蟲失敗：{e}", "count": 0, "sample_titles": []}
    if source.type == "website":
        # website 型：呼叫對應爬蟲測試
        from backend.services.cnyes_scraper import is_cnyes_api_url, fetch_cnyes_from_url
        from backend.services.worldbank_scraper import is_worldbank_api_url, fetch_worldbank_news
        from backend.services.fsc_scraper import is_fsc_url, fetch_fsc_news
        from backend.services.caixin_scraper import is_caixin_url, fetch_caixin_news
        from backend.services.storm_scraper import is_storm_url, fetch_storm_news
        from backend.services.taisounds_scraper import is_taisounds_url, fetch_taisounds_news
        from backend.services.linetoday_scraper import is_linetoday_url, fetch_linetoday_news
        from backend.services.udn_scraper import is_udn_cate_url, fetch_udn_cate_news

        # 路由到對應爬蟲
        scraper_map = [
            (is_cnyes_api_url, lambda: fetch_cnyes_from_url(source.url, hours_back=24), "鉅亨網 JSON API"),
            (is_worldbank_api_url, lambda: fetch_worldbank_news(source.url, hours_back=48), "World Bank API"),
            (is_fsc_url, lambda: fetch_fsc_news(hours_back=48), "金管會新聞稿"),
            (is_caixin_url, lambda: fetch_caixin_news(hours_back=48), "財新 Caixin Global"),
            (is_storm_url, lambda: fetch_storm_news(hours_back=24), "風傳媒 News Sitemap"),
            (is_taisounds_url, lambda: fetch_taisounds_news(hours_back=24), "太報 Sitemap"),
            (is_linetoday_url, lambda: fetch_linetoday_news(hours_back=24), "LINE Today 國際"),
            (is_udn_cate_url, lambda: fetch_udn_cate_news(source.url, hours_back=24), "聯合新聞網分類頁"),
        ]
        for check_fn, fetch_fn, label in scraper_map:
            if check_fn(source.url):
                try:
                    articles = await fetch_fn()
                    titles = [a["title"][:60] for a in articles[:5]]
                    return {"success": True, "count": len(articles), "feed_title": label,
                            "sample_titles": titles if titles else ["時間範圍內無文章"], "error": None}
                except Exception as e:
                    return {"success": False, "error": f"{label} 錯誤：{e}", "count": 0, "sample_titles": []}

        # 其他 website：基本 HTTP 連線測試
        try:
            async with httpx.AsyncClient(timeout=10, verify=False, follow_redirects=True) as client:
                resp = await client.get(source.url, headers={"User-Agent": "Mozilla/5.0 (compatible; FinancialRadar/1.0)"})
                resp.raise_for_status()
            return {"success": True, "count": -1, "feed_title": "網頁",
                    "sample_titles": [f"HTTP {resp.status_code} — 連線正常（網頁型無法預覽文章）"], "error": None}
        except Exception as e:
            return {"success": False, "error": f"連線失敗：{e}", "count": 0, "sample_titles": []}
    if source.type not in ("rss", "social"):
        return {"success": False, "error": f"類型「{source.type}」不支援此測試", "count": 0, "sample_titles": []}
    # 提早偵測 MOPS URL（使用者可能填錯類型）
    if "mops.twse.com.tw" in source.url:
        return {"success": False,
                "error": "此 URL 屬於公開資訊觀測站，非 RSS。請將來源類型改為「MOPS」，或刪除此來源改用系統內建的「公開資訊觀測站重大訊息」。",
                "count": 0, "sample_titles": []}

    try:
        async with httpx.AsyncClient(timeout=15, verify=False, follow_redirects=True) as client:
            resp = await client.get(
                source.url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; FinancialRadar/1.0)"},
            )
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        total = len(feed.entries)

        if total == 0:
            feed_title = feed.feed.get("title", "")
            if feed_title:
                return {
                    "success": False,
                    "error": f'RSS 解析正常（{feed_title}），但目前無條目',
                    "count": 0,
                    "sample_titles": [],
                }
            return {
                "success": False,
                "error": "此 URL 不是有效的 RSS Feed（可能輸入了網站首頁 URL，請改用 RSS 訂閱網址）",
                "count": 0,
                "sample_titles": [],
            }

        sample_titles = [e.get("title", "（無標題）") for e in feed.entries[:5]]

        # 檢查 feed 是否過期（最新文章超過 48 小時 = 可能已停止更新）
        import calendar
        stale_warning = None
        for entry in feed.entries[:3]:
            for attr in ("published_parsed", "updated_parsed"):
                parsed = getattr(entry, attr, None)
                if parsed:
                    try:
                        from datetime import datetime, timedelta
                        entry_dt = datetime.utcfromtimestamp(calendar.timegm(parsed))
                        age_hours = (datetime.utcnow() - entry_dt).total_seconds() / 3600
                        if age_hours > 48:
                            age_days = int(age_hours / 24)
                            stale_warning = f"⚠️ 此 RSS 最新文章為 {age_days} 天前，可能已停止更新。實際掃描時這些舊文會被時間過濾擋掉，不會進入雷達。建議改用 Google News 代理（類型改 RSS，URL 用 https://news.google.com/rss/search?q=site:wsj.com+when:7d&hl=en&gl=US）"
                    except Exception:
                        pass
                    break
            if stale_warning:
                break

        return {
            "success": True if not stale_warning else False,
            "count": total,
            "feed_title": feed.feed.get("title", ""),
            "sample_titles": sample_titles,
            "error": stale_warning,
        }

    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code} 錯誤，請確認 URL 是否正確",
            "count": 0,
            "sample_titles": [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"連線失敗：{str(e)[:150]}",
            "count": 0,
            "sample_titles": [],
        }


# --- 財經相關性篩選設定 ---

class FinanceFilterRequest(BaseModel):
    enabled: bool = False
    threshold: float = 0.15


@router.get("/finance-filter")
async def get_finance_filter(db: Session = Depends(get_db)):
    """取得財經相關性篩選設定。"""
    enabled = _get_config(db, "finance_filter_enabled", "false") == "true"
    try:
        threshold = float(_get_config(db, "finance_relevance_threshold", "0.15"))
    except (ValueError, TypeError):
        threshold = 0.15
    return {"enabled": enabled, "threshold": threshold}


@router.put("/finance-filter")
async def update_finance_filter(req: FinanceFilterRequest, db: Session = Depends(get_db)):
    """更新財經相關性篩選設定。"""
    _set_config(db, "finance_filter_enabled", "true" if req.enabled else "false")
    _set_config(db, "finance_relevance_threshold", str(round(max(0.0, min(req.threshold, 1.0)), 4)))
    db.commit()
    return {"enabled": req.enabled, "threshold": req.threshold}


# --- RSS 優先模式設定 ---

class RssMinArticlesRequest(BaseModel):
    min_articles: int = 0  # 0 = 停用 RSS 優先（維持原有行為）


@router.get("/rss-priority")
async def get_rss_priority(db: Session = Depends(get_db)):
    """取得 RSS 優先模式設定（min_articles=0 表示停用）。"""
    try:
        min_articles = int(_get_config(db, "radar_rss_min_articles", "0"))
    except (ValueError, TypeError):
        min_articles = 0
    return {"min_articles": min_articles}


@router.put("/rss-priority")
async def update_rss_priority(req: RssMinArticlesRequest, db: Session = Depends(get_db)):
    """更新 RSS 優先模式門檻（min_articles=0 停用，>0 啟用）。"""
    _set_config(db, "radar_rss_min_articles", str(max(0, req.min_articles)))
    db.commit()
    return {"min_articles": req.min_articles}


# --- Google News 僅緊急模式 ---

class GnCriticalOnlyRequest(BaseModel):
    enabled: bool = False


@router.get("/gn-critical-only")
async def get_gn_critical_only(db: Session = Depends(get_db)):
    """取得 Google News 僅緊急模式設定。"""
    enabled = _get_config(db, "gn_critical_only", "false") == "true"
    return {"enabled": enabled}


@router.put("/gn-critical-only")
async def update_gn_critical_only(req: GnCriticalOnlyRequest, db: Session = Depends(get_db)):
    """更新 Google News 僅緊急模式（啟用時 GN 文章只保留緊急，RSS 不受影響）。"""
    _set_config(db, "gn_critical_only", "true" if req.enabled else "false")
    db.commit()
    return {"enabled": req.enabled}
