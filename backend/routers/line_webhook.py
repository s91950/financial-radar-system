"""LINE Webhook 接收端點。

使用者傳訊息給 LINE Bot → LINE 呼叫此端點 → Bot 用 Reply API 回覆最新警報。
Reply API 完全免費，不計入每月 200 則 Messaging API 配額。

設定步驟：
1. 在 .env 填入 LINE_CHANNEL_SECRET（與 LINE_CHANNEL_ACCESS_TOKEN 同一個 Channel）
2. 開啟 ngrok：ngrok http 8000
3. 在 LINE Developers Console 將 Webhook URL 設為：
   https://[ngrok-domain].ngrok-free.app/api/line/webhook
4. 開啟「Use webhook」開關
5. 傳任意訊息給 LINE Bot 即可收到最新警報回覆
"""

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from backend.config import settings
from backend.database import Alert, SessionLocal, SystemConfig
from backend.services.notification import send_line_reply_multi

# UTC+8（台灣時區）
_TZ_HOURS = 8

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE Webhook 簽名（HMAC-SHA256）。"""
    secret = settings.LINE_CHANNEL_SECRET
    if not secret:
        # 未設定 secret 時略過驗證（開發測試用途）
        logger.warning("LINE_CHANNEL_SECRET 未設定，跳過簽名驗證")
        return True
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _clean_url(url: str) -> str:
    """移除 {severity} 前綴並過濾 Google 搜尋 URL。"""
    clean = re.sub(r'^\{[^}]+\}', '', url).strip()
    return clean if "google.com/search" not in clean else ""


def _parse_articles(alert, only_severity: str = "critical") -> list[tuple[str, str]]:
    """從 alert 解析 (標題, URL) 配對清單，只取指定嚴重度的文章。

    保留原始行號與 URL 索引的對應關係，確保 URL 不錯位。
    """
    content_lines = [l.strip() for l in (alert.content or "").splitlines() if l.strip()]
    raw_urls = json.loads(alert.source_urls) if alert.source_urls else []
    url_at_index = [_clean_url(raw) for raw in raw_urls]  # 保持原始索引，空字串仍佔位

    results = []
    for i, line in enumerate(content_lines):
        # 嚴重度篩選：只保留 only_severity 的文章
        sev_m = re.match(r'^\{(critical|high|medium|low)\}', line)
        line_sev = sev_m.group(1) if sev_m else "low"
        if line_sev != only_severity:
            continue

        # 清理標題
        t = re.sub(r'^\{[^}]+\}', '', line).strip()
        t = re.sub(r'^\[[^\]]+\]\s*', '', t).strip()
        t = re.sub(r'\s*[（(]關鍵字[：:][^)）]*[)）]', '', t).strip()
        if t:
            url = url_at_index[i] if i < len(url_at_index) else ""
            results.append((t, url))

    return results


def _get_last_reply_time(db) -> datetime | None:
    """從 SystemConfig 讀取上次 Bot 回覆時間（UTC）。"""
    row = db.query(SystemConfig).filter(SystemConfig.key == "line_last_reply_at").first()
    if not row or not row.value:
        return None
    try:
        return datetime.fromisoformat(row.value)
    except ValueError:
        return None


def _set_last_reply_time(db, dt: datetime):
    """更新 SystemConfig 的 line_last_reply_at。"""
    row = db.query(SystemConfig).filter(SystemConfig.key == "line_last_reply_at").first()
    if row:
        row.value = dt.isoformat()
    else:
        db.add(SystemConfig(key="line_last_reply_at", value=dt.isoformat()))
    db.commit()


def _utc_to_local_str(dt: datetime) -> str:
    """UTC datetime → UTC+8 顯示字串。"""
    return (dt + timedelta(hours=_TZ_HOURS)).strftime("%m/%d %H:%M")


def _parse_time_range(text: str) -> timedelta | None:
    """從訊息文字解析自訂時間範圍，回傳 timedelta 或 None（代表「未讀模式」）。

    支援格式：
      1小時 / 過去1小時 / 3小時
      1天 / 今天 / 今日 / 24小時
      2天 / 過去2天
    """
    # X 小時
    m = re.search(r'(\d+)\s*小時', text)
    if m:
        return timedelta(hours=int(m.group(1)))
    # 今天 / 今日
    if re.search(r'今[天日]', text):
        return timedelta(hours=24)
    # X 天
    m = re.search(r'(\d+)\s*天', text)
    if m:
        return timedelta(days=int(m.group(1)))
    return None


_ARTICLES_PER_MSG = 30  # 每則 LINE 訊息最多顯示幾篇文章


def _build_critical_reply(alerts: list, since: datetime | None, label: str | None = None) -> list[str]:
    """格式化緊急警報，回傳 LINE 多訊息清單（最多 5 則，每則 15 篇文章）。

    since: UTC 基準時間（顯示用）
    label: 自訂標頭說明（如「過去 1 小時」），None 代表「未讀模式」
    """
    if not alerts:
        if label:
            return [f"過去 {label} 內沒有緊急警報。"]
        if since:
            return [f"自 {_utc_to_local_str(since)} 起沒有新的緊急警報。"]
        return ["目前沒有緊急警報。"]

    # 收集所有警報的文章（去重）
    seen_titles: set[str] = set()
    all_articles: list[tuple[str, str]] = []
    for a in alerts:
        for title, url in _parse_articles(a):
            if title not in seen_titles:
                seen_titles.add(title)
                all_articles.append((title, url))

    total = len(all_articles)
    if label:
        header = f"[過去 {label} {total} 則緊急新聞]"
    else:
        since_str = _utc_to_local_str(since) if since else "–"
        header = f"[{since_str} 後 {total} 則緊急新聞]"

    # 分批：每批 _ARTICLES_PER_MSG 篇，最多 5 批（LINE Reply 上限）
    messages: list[str] = []
    chunks = [all_articles[i:i + _ARTICLES_PER_MSG] for i in range(0, total, _ARTICLES_PER_MSG)]
    for batch_idx, chunk in enumerate(chunks[:5]):
        lines = []
        if batch_idx == 0:
            lines.append(header)
        else:
            start_num = batch_idx * _ARTICLES_PER_MSG + 1
            lines.append(f"（續 {start_num}～{start_num + len(chunk) - 1}）")
        for i, (title, url) in enumerate(chunk, start=batch_idx * _ARTICLES_PER_MSG + 1):
            lines.append(f"\n{i}) {title}")
            if url:
                lines.append(url)
        messages.append("\n".join(lines))

    return messages


@router.post("/line/webhook")
async def line_webhook(request: Request):
    """接收 LINE Webhook 事件並用 Reply API 回覆（免費無月額限制）。"""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = payload.get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue
        reply_token = event.get("replyToken")
        if not reply_token:
            continue

        msg_obj = event.get("message", {})
        user_text = msg_obj.get("text", "").strip() if msg_obj.get("type") == "text" else ""

        db = SessionLocal()
        try:
            time_range = _parse_time_range(user_text)

            if time_range:
                # ── 自訂時間範圍模式（不更新「上次已讀」時間）──
                since_dt = datetime.utcnow() - time_range
                alerts = (
                    db.query(Alert)
                    .filter(Alert.severity == "critical")
                    .filter(Alert.created_at >= since_dt)
                    .order_by(Alert.created_at.asc())
                    .all()
                )
                # 組成人類可讀標籤（如「1 小時」「今天」）
                total_seconds = int(time_range.total_seconds())
                if total_seconds <= 3600:
                    range_label = f"{total_seconds // 3600 or 1} 小時"
                elif total_seconds < 86400:
                    range_label = f"{total_seconds // 3600} 小時"
                else:
                    range_label = f"{time_range.days} 天"
                reply_text = _build_critical_reply(alerts, since_dt, label=range_label)
            else:
                # ── 未讀模式：自上次 Bot 回覆後的新警報 ──
                since = _get_last_reply_time(db)
                query = db.query(Alert).filter(Alert.severity == "critical")
                if since:
                    query = query.filter(Alert.created_at > since)
                alerts = query.order_by(Alert.created_at.asc()).all()
                reply_text = _build_critical_reply(alerts, since)
                # 更新已讀時間
                _set_last_reply_time(db, datetime.utcnow())
        finally:
            db.close()

        await send_line_reply_multi(reply_token, reply_text)

    # LINE 要求回傳 200 OK
    return {"status": "ok"}
