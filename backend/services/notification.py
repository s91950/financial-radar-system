"""Notification service for Line Notify, Email, and WebSocket."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


async def send_line_notify(message: str, token: str | None = None) -> bool:
    """Send a message via LINE Notify."""
    token = token or settings.LINE_NOTIFY_TOKEN
    if not token or token == "your_line_notify_token_here":
        logger.warning("LINE Notify token not set")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {token}"},
                data={"message": message[:1000]},  # LINE limit
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"LINE Notify error: {e}")
        return False


async def send_line_broadcast(message: str) -> bool:
    """透過 LINE Messaging API 傳送通知。

    優先使用 Push（LINE_TARGET_ID 指定對象），不受每月廣播限額限制。
    若未設 LINE_TARGET_ID 才改用 Broadcast（需用戶加 bot 為好友）。
    """
    token = settings.LINE_CHANNEL_ACCESS_TOKEN
    if not token or token in ("", "your_line_channel_access_token_here"):
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 未設定")
        return False

    # 優先用 Push（指定 TARGET_ID，適用大多數方案）
    target_id = settings.LINE_TARGET_ID
    if target_id and target_id not in ("", "your_line_user_id_here", "your_line_target_id_here"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"to": target_id, "messages": [{"type": "text", "text": message[:4900]}]},
                )
                if resp.status_code == 429:
                    body = resp.json()
                    logger.error(f"LINE push 達到上限: {body.get('message', resp.text)}")
                    return False
                resp.raise_for_status()
                return True
        except httpx.HTTPStatusError as e:
            logger.error(f"LINE push HTTP 錯誤 {e.response.status_code}: {e.response.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"LINE push 錯誤: {e}")
            return False

    # 無 TARGET_ID 時 fallback 到 Broadcast
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.line.me/v2/bot/message/broadcast",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"messages": [{"type": "text", "text": message[:4900]}]},
            )
            if resp.status_code == 429:
                body = resp.json()
                logger.error(f"LINE broadcast 達到上限: {body.get('message', resp.text)}")
                return False
            resp.raise_for_status()
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"LINE broadcast HTTP 錯誤 {e.response.status_code}: {e.response.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"LINE broadcast 錯誤: {e}")
        return False


async def send_line_message(message: str) -> bool:
    """透過 LINE Messaging API Push 傳送給指定對象（向下相容保留）。

    需要 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_TARGET_ID。
    建議改用 send_line_broadcast 以支援所有好友。
    """
    token = settings.LINE_CHANNEL_ACCESS_TOKEN
    target_id = settings.LINE_TARGET_ID
    if not token or token in ("", "your_line_channel_access_token_here"):
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 未設定")
        return False
    if not target_id or target_id in ("", "your_line_user_id_here", "your_line_target_id_here"):
        logger.warning("LINE_TARGET_ID 未設定，改用 broadcast 傳送")
        return await send_line_broadcast(message)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": target_id,
                    "messages": [{"type": "text", "text": message[:4900]}],
                },
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"LINE push 錯誤: {e}")
        return False


async def send_email(
    subject: str,
    body: str,
    recipient: str | None = None,
    is_html: bool = True,
) -> bool:
    """Send an email notification via SMTP."""
    if not settings.EMAIL_SENDER or not settings.EMAIL_PASSWORD:
        logger.warning("Email credentials not set")
        return False

    recipient = recipient or settings.EMAIL_RECIPIENT
    if not recipient:
        logger.warning("Email recipient not set")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.EMAIL_SENDER
        msg["To"] = recipient
        msg["Subject"] = subject

        content_type = "html" if is_html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.EMAIL_SMTP_HOST,
            port=settings.EMAIL_SMTP_PORT,
            start_tls=True,
            username=settings.EMAIL_SENDER,
            password=settings.EMAIL_PASSWORD,
        )
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False


_SEV_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
_SEV_LABEL = {"critical": "緊急", "high": "高", "medium": "中", "low": "低"}
import re as _re


def _parse_content_line(line: str) -> tuple[str, str]:
    """Return (severity_emoji, clean_line) stripping {severity} prefix."""
    m = _re.match(r'^\{(critical|high|medium|low)\}(.*)', line)
    if m:
        return _SEV_EMOJI.get(m.group(1), "🟢"), m.group(2).strip()
    return "🟢", line.strip()


def _clean_url(url: str) -> str:
    """Strip {severity} prefix from URL."""
    return _re.sub(r'^\{[^}]+\}', '', url).strip()


_SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _item_severity(text: str) -> str:
    """Extract severity level from {severity} prefix on a content line or URL."""
    m = _re.match(r'^\{(critical|high|medium|low)\}', text)
    return m.group(1) if m else "low"


def format_alert_message(alert: dict, min_severity: str = "all") -> str:
    """Format an alert dict into a structured notification message (LINE-friendly).

    min_severity: 只顯示嚴重度 >= 此值的文章和來源連結（'all'=全部顯示）
    """
    min_rank = _SEV_RANK.get(min_severity, 0) if min_severity != "all" else 0

    severity = alert.get("severity", "low")
    emoji = _SEV_EMOJI.get(severity, "⚪")
    label = _SEV_LABEL.get(severity, severity)

    parts = [f"{emoji}【{label}】{alert.get('title', 'Alert')}"]

    # Section 1: 發生什麼事
    # 若有 severity 篩選，強制使用文章清單（AI 摘要涵蓋所有文章，無法按嚴重度過濾）
    ai = alert.get("ai_structured") or {}
    event_summary = ai.get("event_summary", "")
    if event_summary and min_rank == 0:
        parts.append(f"\n📌 發生什麼事\n{event_summary[:400]}")
    else:
        # 文章清單，依 min_severity 篩選
        raw_lines = [l for l in (alert.get("content") or "").splitlines() if l.strip()]
        if raw_lines:
            if min_rank > 0:
                shown_lines = [l for l in raw_lines if _SEV_RANK.get(_item_severity(l), 0) >= min_rank]
                skipped = len(raw_lines) - len(shown_lines)
            else:
                shown_lines = raw_lines
                skipped = 0

            if shown_lines:
                parts.append("\n📰 偵測到的新聞")
                for line in shown_lines[:5]:
                    sev_em, clean = _parse_content_line(line)
                    parts.append(f"{sev_em} {clean}")
                if len(shown_lines) > 5:
                    parts.append(f"  …等共 {len(shown_lines)} 則")

    # Section 2: 部位暴險
    exposure = ai.get("exposure_analysis") or alert.get("exposure_summary", "")
    if exposure:
        parts.append(f"\n💼 部位暴險\n{exposure[:300]}")

    # Section 3: 後續發展
    follow_up = ai.get("follow_up", "")
    if follow_up:
        parts.append(f"\n🔮 後續發展\n{follow_up[:300]}")

    # Section 4: 來源（filter by min_severity, strip prefix, skip google search URLs）
    raw_urls = alert.get("source_urls") or []
    if min_rank > 0:
        raw_urls = [u for u in raw_urls if u and _SEV_RANK.get(_item_severity(u), 0) >= min_rank]
    clean_urls = [_clean_url(u) for u in raw_urls if u]
    # 優先顯示真實文章 URL（含 news.google.com/articles/ 可點擊連結），
    # 排除 google.com/search?q=... 這類不友好的搜尋 URL
    real_urls = [u for u in clean_urls if "google.com/search" not in u]
    display_urls = real_urls  # 若全為 search URL 則不顯示（比顯示一堆編碼 URL 好）
    if display_urls:
        parts.append("\n🔗 來源")
        for url in display_urls[:3]:
            parts.append(f"• {url}")

    return "\n".join(parts)


def format_alert_email(alert: dict) -> str:
    """Format an alert dict into an HTML email body with 4-section AI layout."""
    severity_colors = {
        "low": "#4CAF50",
        "medium": "#FF9800",
        "high": "#FF5722",
        "critical": "#F44336",
    }
    color = severity_colors.get(alert.get("severity", ""), "#9E9E9E")

    ai = alert.get("ai_structured") or {}
    event_summary = ai.get("event_summary") or alert.get("content", "")
    exposure_ai = ai.get("exposure_analysis") or alert.get("exposure_summary", "")
    follow_up = ai.get("follow_up", "")

    exposure_html = ""
    if exposure_ai:
        exposure_html = f"""
            <div style="background: #FFF3E0; padding: 12px; border-radius: 6px; margin: 12px 0;">
                <strong>💼 部位暴險</strong>
                <div style="margin: 8px 0 0; white-space: pre-wrap;">{exposure_ai}</div>
            </div>"""

    follow_up_html = ""
    if follow_up:
        follow_up_html = f"""
            <div style="background: #E3F2FD; padding: 12px; border-radius: 6px; margin: 12px 0;">
                <strong>🔮 後續發展</strong>
                <div style="margin: 8px 0 0; white-space: pre-wrap;">{follow_up}</div>
            </div>"""

    sources_html = ""
    raw_source_urls = alert.get("source_urls") or []
    # 只顯示真實文章 URL（過濾 google.com/search 搜尋 URL）
    display_source_urls = [
        _clean_url(u) for u in raw_source_urls
        if u and "google.com/search" not in _clean_url(u)
    ]
    if display_source_urls:
        links = "".join(
            f'<li><a href="{url}" style="color: #1976D2;">{url[:80]}</a></li>'
            for url in display_source_urls[:5]
        )
        sources_html = f'<div style="margin-top: 12px;"><strong>🔗 資料來源</strong><ul>{links}</ul></div>'

    from backend.config import settings
    model_label = "Gemini" if settings.DEFAULT_AI_MODEL == "gemini" else "Claude"

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {color}; color: white; padding: 12px 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">⚡ 金融偵測警報</h2>
            <span style="opacity: 0.9;">{alert.get('severity', '').upper()}</span>
        </div>
        <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
            <h3>{alert.get('title', '')}</h3>
            <div style="background: #F5F5F5; padding: 12px; border-radius: 6px; margin: 12px 0;">
                <strong>📌 發生什麼事</strong>
                <div style="margin: 8px 0 0; white-space: pre-wrap;">{event_summary}</div>
            </div>
            {exposure_html}
            {follow_up_html}
            {sources_html}
            <p style="color: #999; font-size: 12px; margin-top: 16px;">[{model_label} 自動分析] 登入系統可切換 Claude 深度分析</p>
        </div>
    </div>
    """


# ──────────────────────────────────────────────
# Discord Webhook
# ──────────────────────────────────────────────

_SEV_DISCORD_COLOR = {
    "critical": 0xFF0000,
    "high": 0xFF8C00,
    "medium": 0xFFD700,
    "low": 0x95A5A6,
}


def format_alert_discord(alert: dict) -> dict:
    """Format an alert dict into a Discord Embed object."""
    severity = alert.get("severity", "low")
    color = _SEV_DISCORD_COLOR.get(severity, 0x95A5A6)
    label = _SEV_LABEL.get(severity, severity)
    emoji = _SEV_EMOJI.get(severity, "⚪")

    ai = alert.get("ai_structured") or {}
    event_summary = ai.get("event_summary") or alert.get("content", "")
    exposure = ai.get("exposure_analysis") or alert.get("exposure_summary", "")
    follow_up = ai.get("follow_up", "")

    fields = []

    if event_summary:
        fields.append({
            "name": "📌 發生什麼事",
            "value": event_summary[:1024],
            "inline": False,
        })

    if exposure:
        fields.append({
            "name": "💼 部位暴險",
            "value": exposure[:1024],
            "inline": False,
        })

    if follow_up:
        fields.append({
            "name": "🔮 後續發展",
            "value": follow_up[:1024],
            "inline": False,
        })

    # 來源連結（最多 3 個，過濾 google search URL）
    raw_urls = alert.get("source_urls") or []
    real_urls = [_clean_url(u) for u in raw_urls if u and "google.com/search" not in _clean_url(u)]
    if real_urls:
        links = "\n".join(f"• {u}" for u in real_urls[:3])
        fields.append({"name": "🔗 來源", "value": links[:1024], "inline": False})

    embed = {
        "title": f"{emoji}【{label}】{alert.get('title', 'Alert')}",
        "color": color,
        "fields": fields,
        "footer": {"text": "金融即時偵測系統"},
    }
    return embed


async def send_discord_webhook(webhook_url: str, alert_dict: dict) -> bool:
    """POST an alert as a Discord Embed to the given webhook URL."""
    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        logger.warning("Discord webhook URL 未設定或格式不正確")
        return False
    try:
        embed = format_alert_discord(alert_dict)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"embeds": [embed]})
            if resp.status_code == 204:
                return True
            resp.raise_for_status()
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Discord webhook HTTP 錯誤 {e.response.status_code}: {e.response.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Discord webhook 錯誤: {e}")
        return False


# ──────────────────────────────────────────────
# LINE Reply API（免費、不計入月額）
# ──────────────────────────────────────────────


async def send_line_reply(reply_token: str, message: str) -> bool:
    """透過 LINE Reply API 回覆訊息（完全免費，不計入每月 200 則配額）。"""
    return await send_line_reply_multi(reply_token, [message])


async def send_line_reply_multi(reply_token: str, messages: list[str]) -> bool:
    """透過 LINE Reply API 一次回覆多則訊息（最多 5 則，每則 5000 字元）。

    reply_token 由 LINE Webhook 事件提供，有效期約 30 秒。
    """
    token = settings.LINE_CHANNEL_ACCESS_TOKEN
    if not token or token in ("", "your_line_channel_access_token_here"):
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 未設定，無法使用 Reply API")
        return False
    if not messages:
        return False
    msg_objects = [{"type": "text", "text": m[:5000]} for m in messages[:5]]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.line.me/v2/bot/message/reply",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"replyToken": reply_token, "messages": msg_objects},
            )
            if resp.status_code == 400:
                logger.warning(f"LINE Reply API 400: {resp.text[:200]}")
                return False
            resp.raise_for_status()
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"LINE Reply API HTTP 錯誤 {e.response.status_code}: {e.response.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"LINE Reply API 錯誤: {e}")
        return False
