"""LINE Webhook 接收端點。

使用者傳訊息給 LINE Bot → LINE 呼叫此端點 → Bot 用 Reply API 回覆。
Reply API 完全免費，不計入每月 200 則 Messaging API 配額。

支援指令：
  通知          → 未讀緊急新聞警報（自上次查詢後）
  通知 + 時間   → 指定時間範圍的緊急新聞（如：通知1天、通知今日、通知3小時）
  分析          → 最新 NotebookLM 新聞分析報告
  yt / YT       → 未讀 YouTube 影片
  yt + 時間     → 指定時間範圍的 YouTube 影片（如：yt1天、yt今日、yt通知）
  yt分析        → 最新 NotebookLM YouTube 頻道分析報告
  其他訊息       → 不回應

設定步驟：
1. 在 .env 填入 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN
2. 在 LINE Developers Console 將 Webhook URL 設為：
   http://[VM_IP]/api/line/webhook
3. 開啟「Use webhook」開關
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
from backend.database import Alert, SessionLocal, SystemConfig, YoutubeVideo
from backend.services.notification import send_line_reply_multi

_TZ_HOURS = 8

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE Webhook 簽名（HMAC-SHA256）。"""
    secret = settings.LINE_CHANNEL_SECRET
    if not secret:
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
    """從 alert 解析 (標題, URL) 配對清單，只取指定嚴重度的文章。"""
    content_lines = [l.strip() for l in (alert.content or "").splitlines() if l.strip()]
    raw_urls = json.loads(alert.source_urls) if alert.source_urls else []
    url_at_index = [_clean_url(raw) for raw in raw_urls]

    results = []
    for i, line in enumerate(content_lines):
        sev_m = re.match(r'^\{(critical|high|medium|low)\}', line)
        line_sev = sev_m.group(1) if sev_m else "low"
        if line_sev != only_severity:
            continue
        t = re.sub(r'^\{[^}]+\}', '', line).strip()
        t = re.sub(r'^\[[^\]]+\]\s*', '', t).strip()
        t = re.sub(r'\s*[（(]關鍵字[：:][^)）]*[)）]', '', t).strip()
        if t:
            url = url_at_index[i] if i < len(url_at_index) else ""
            results.append((t, url))
    return results


def _get_config(db, key: str) -> datetime | None:
    """從 SystemConfig 讀取 datetime 欄位。"""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if not row or not row.value:
        return None
    try:
        return datetime.fromisoformat(row.value)
    except ValueError:
        return None


def _set_config(db, key: str, dt: datetime):
    """更新 SystemConfig 的 datetime 欄位。"""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row:
        row.value = dt.isoformat()
    else:
        db.add(SystemConfig(key=key, value=dt.isoformat()))
    db.commit()


def _utc_to_local_str(dt: datetime) -> str:
    """UTC datetime → UTC+8 顯示字串。"""
    return (dt + timedelta(hours=_TZ_HOURS)).strftime("%m/%d %H:%M")


def _parse_time_range(text: str) -> timedelta | None:
    """從訊息文字解析時間範圍，回傳 timedelta 或 None。

    支援：1小時 / 3小時 / 今天 / 今日 / 1天 / 2天
    """
    m = re.search(r'(\d+)\s*小時', text)
    if m:
        return timedelta(hours=int(m.group(1)))
    if re.search(r'今[天日]', text):
        return timedelta(hours=24)
    m = re.search(r'(\d+)\s*天', text)
    if m:
        return timedelta(days=int(m.group(1)))
    return None


_ARTICLES_PER_MSG = 30
_ANALYSIS_MAX_CHARS = 4800  # LINE 單訊息上限約 5000，留緩衝


def _md_to_plain(text: str) -> str:
    """將 Markdown 轉換為 LINE 可讀純文字（移除標記符號）。"""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)   # 標題
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)        # 粗/斜體
    text = re.sub(r'^\|[-:| ]+\|$', '', text, flags=re.MULTILINE) # 表格分隔列
    text = re.sub(r'^\|(.+)\|$',
                  lambda m: '  '.join(c.strip() for c in m.group(1).split('|') if c.strip()),
                  text, flags=re.MULTILINE)                        # 表格內容
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)          # 引用
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)         # 分隔線
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _build_analysis_reply(
    content: str | None,
    generated_at: str | None,
    title: str = "📊 金融風險分析報告",
) -> list[str]:
    """格式化 NLM 分析報告為 LINE 訊息（最多 5 則）。"""
    if not content:
        return ["目前尚無分析報告，請稍後再試或先執行 notebooklm_hourly.py。"]

    time_str = ""
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            time_str = (dt + timedelta(hours=_TZ_HOURS)).strftime("%m/%d %H:%M")
        except Exception:
            time_str = generated_at[:16]

    header = f"{title} {time_str}\n{'─' * 22}\n\n"
    plain = _md_to_plain(content)

    messages: list[str] = []
    first = header + plain[:_ANALYSIS_MAX_CHARS - len(header)]
    messages.append(first)
    remaining = plain[_ANALYSIS_MAX_CHARS - len(header):]
    while remaining and len(messages) < 5:
        messages.append(remaining[:_ANALYSIS_MAX_CHARS])
        remaining = remaining[_ANALYSIS_MAX_CHARS:]
    return messages


def _build_news_reply(alerts: list, since: datetime | None, label: str | None = None) -> list[str]:
    """格式化緊急新聞警報，回傳 LINE 多訊息清單（最多 5 則）。"""
    if not alerts:
        if label:
            return [f"過去 {label} 內沒有緊急警報。"]
        if since:
            return [f"自 {_utc_to_local_str(since)} 起沒有新的緊急警報。"]
        return ["目前沒有緊急警報。"]

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


_VIDEOS_PER_MSG = 10


def _build_yt_reply(videos: list, since: datetime | None, label: str | None = None) -> list[str]:
    """格式化 YouTube 影片清單，回傳 LINE 多訊息清單（最多 5 則）。"""
    if not videos:
        if label:
            return [f"過去 {label} 內沒有新的 YouTube 影片。"]
        if since:
            return [f"自 {_utc_to_local_str(since)} 起沒有新的 YouTube 影片。"]
        return ["目前沒有未讀 YouTube 影片。"]

    total = len(videos)
    if label:
        header = f"[過去 {label} {total} 部 YouTube 影片]"
    else:
        since_str = _utc_to_local_str(since) if since else "–"
        header = f"[{since_str} 後 {total} 部 YouTube 影片]"

    messages: list[str] = []
    chunks = [videos[i:i + _VIDEOS_PER_MSG] for i in range(0, total, _VIDEOS_PER_MSG)]
    for batch_idx, chunk in enumerate(chunks[:5]):
        lines = []
        if batch_idx == 0:
            lines.append(header)
        else:
            start_num = batch_idx * _VIDEOS_PER_MSG + 1
            lines.append(f"（續 {start_num}～{start_num + len(chunk) - 1}）")
        for i, v in enumerate(chunk, start=batch_idx * _VIDEOS_PER_MSG + 1):
            pub = _utc_to_local_str(v.published_at) if v.published_at else ""
            lines.append(f"\n{i}) {v.title or '無標題'}")
            if pub:
                lines.append(f"   {pub}")
            if v.url:
                lines.append(v.url)
        messages.append("\n".join(lines))

    return messages


@router.post("/line/webhook")
async def line_webhook(request: Request):
    """接收 LINE Webhook 事件並用 Reply API 回覆（免費無月額限制）。

    指令：
      分析        → 最新 NotebookLM 新聞分析報告
      通知        → 未讀緊急新聞
      通知 + 時間  → 指定時間範圍新聞
      yt/YT       → 未讀 YouTube 影片
      yt + 時間   → 指定時間範圍 YouTube 影片
      yt分析      → 最新 NotebookLM YouTube 頻道分析報告
      其他        → 不回應
    """
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

        if not user_text:
            continue

        # 判斷模式：yt 開頭 / 分析 / 通知
        is_yt = user_text[:2].lower() == "yt"
        is_analysis = not is_yt and "分析" in user_text
        is_news = not is_yt and not is_analysis and "通知" in user_text

        if not is_yt and not is_analysis and not is_news:
            continue

        db = SessionLocal()
        try:
            if is_analysis:
                # ── 新聞分析報告模式 ──
                def _cfg(key):
                    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
                    return row.value if row else None

                reply_text = _build_analysis_reply(
                    _cfg("nlm_latest_report"),
                    _cfg("nlm_report_generated_at"),
                )

            elif is_yt:
                # ── YouTube 模式 ──
                remainder = user_text[2:].strip()  # 去掉 "yt" 前綴

                if "分析" in remainder:
                    # yt分析 → YT 頻道分析報告
                    def _cfg_yt(key):
                        row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
                        return row.value if row else None

                    reply_text = _build_analysis_reply(
                        _cfg_yt("nlm_yt_latest_report"),
                        _cfg_yt("nlm_yt_report_generated_at"),
                        title="📺 YouTube 頻道分析報告",
                    )
                else:
                    # yt 影片清單（yt / yt通知 / yt1天 等）
                    time_range = _parse_time_range(remainder)

                    if time_range:
                        # 時間範圍查詢
                        since_dt = datetime.utcnow() - time_range
                        videos = (
                            db.query(YoutubeVideo)
                            .filter(YoutubeVideo.published_at >= since_dt)
                            .order_by(YoutubeVideo.published_at.desc())
                            .all()
                        )
                        total_seconds = int(time_range.total_seconds())
                        if total_seconds <= 3600:
                            range_label = f"{max(1, total_seconds // 3600)} 小時"
                        elif total_seconds < 86400:
                            range_label = f"{total_seconds // 3600} 小時"
                        else:
                            range_label = f"{time_range.days} 天"
                        reply_text = _build_yt_reply(videos, since_dt, label=range_label)
                    else:
                        # 未讀模式（yt 或 yt通知）
                        since = _get_config(db, "line_last_yt_reply_at")
                        query = db.query(YoutubeVideo).filter(YoutubeVideo.is_new == True)
                        if since:
                            query = query.filter(YoutubeVideo.fetched_at > since)
                        videos = query.order_by(YoutubeVideo.published_at.desc()).all()
                        reply_text = _build_yt_reply(videos, since)
                        _set_config(db, "line_last_yt_reply_at", datetime.utcnow())

            else:  # is_news
                # ── 新聞通知模式 ──
                time_range = _parse_time_range(user_text)

                if time_range:
                    since_dt = datetime.utcnow() - time_range
                    alerts = (
                        db.query(Alert)
                        .filter(Alert.severity == "critical")
                        .filter(Alert.created_at >= since_dt)
                        .order_by(Alert.created_at.asc())
                        .all()
                    )
                    total_seconds = int(time_range.total_seconds())
                    if total_seconds <= 3600:
                        range_label = f"{max(1, total_seconds // 3600)} 小時"
                    elif total_seconds < 86400:
                        range_label = f"{total_seconds // 3600} 小時"
                    else:
                        range_label = f"{time_range.days} 天"
                    reply_text = _build_news_reply(alerts, since_dt, label=range_label)
                else:
                    # 未讀模式（通知）
                    since = _get_config(db, "line_last_reply_at")
                    query = db.query(Alert).filter(Alert.severity == "critical")
                    if since:
                        query = query.filter(Alert.created_at > since)
                    alerts = query.order_by(Alert.created_at.asc()).all()
                    reply_text = _build_news_reply(alerts, since)
                    _set_config(db, "line_last_reply_at", datetime.utcnow())

        finally:
            db.close()

        await send_line_reply_multi(reply_token, reply_text)

    return {"status": "ok"}
