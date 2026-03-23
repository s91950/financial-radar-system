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


def format_alert_message(alert: dict) -> str:
    """Format an alert dict into a structured notification message."""
    severity_emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }
    emoji = severity_emoji.get(alert.get("severity", ""), "⚪")

    parts = [
        f"\n{emoji} [{alert.get('severity', 'unknown').upper()}] {alert.get('title', 'Alert')}",
        f"\n📌 事件摘要：",
        f"{alert.get('content', '')[:400]}",
    ]

    exposure = alert.get("exposure_summary")
    if exposure:
        parts.append(f"\n⚠️ 可能影響部位：\n{exposure}")

    source_urls = alert.get("source_urls")
    if source_urls:
        parts.append("\n🔗 資料來源：")
        for url in source_urls[:5]:
            parts.append(f"  {url}")

    parts.append("\n💡 點擊「AI 分析」深入了解後續發展")

    return "\n".join(parts)


def format_alert_email(alert: dict) -> str:
    """Format an alert dict into an HTML email body."""
    severity_colors = {
        "low": "#4CAF50",
        "medium": "#FF9800",
        "high": "#FF5722",
        "critical": "#F44336",
    }
    color = severity_colors.get(alert.get("severity", ""), "#9E9E9E")

    exposure_html = ""
    if alert.get("exposure_summary"):
        exposure_html = f"""
            <div style="background: #FFF3E0; padding: 12px; border-radius: 6px; margin: 12px 0;">
                <strong>⚠️ 可能影響部位：</strong>
                <pre style="margin: 8px 0 0; white-space: pre-wrap;">{alert['exposure_summary']}</pre>
            </div>"""

    sources_html = ""
    if alert.get("source_urls"):
        links = "".join(
            f'<li><a href="{url}" style="color: #1976D2;">{url[:60]}...</a></li>'
            for url in alert["source_urls"][:5]
        )
        sources_html = f'<div style="margin-top: 12px;"><strong>🔗 資料來源：</strong><ul>{links}</ul></div>'

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {color}; color: white; padding: 12px 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">⚡ 金融偵測警報</h2>
            <span style="opacity: 0.9;">{alert.get('severity', '').upper()}</span>
        </div>
        <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
            <h3>{alert.get('title', '')}</h3>
            <p><strong>📌 事件摘要：</strong></p>
            <div style="white-space: pre-wrap;">{alert.get('content', '')}</div>
            {exposure_html}
            {sources_html}
            <p style="color: #666; margin-top: 16px;">💡 登入系統可使用 AI 深度分析</p>
        </div>
    </div>
    """
