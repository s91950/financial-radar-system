"""Google Sheets integration for positions and news archive."""

import logging
import os
from datetime import datetime

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_PLACEHOLDER_IDS = {"", "your_spreadsheet_id_here"}


def _is_configured() -> bool:
    return (
        settings.GOOGLE_SHEETS_SPREADSHEET_ID not in _PLACEHOLDER_IDS
        and os.path.exists(settings.GOOGLE_SHEETS_CREDENTIALS_FILE)
    )


def _get_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        settings.GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=_SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


# --- Position Sheet ---

async def get_positions() -> list[dict]:
    """Read positions from Google Sheet.

    Expected columns: Symbol | 名稱 | 數量 | 均價 | 類別
    """
    if not _is_configured():
        logger.warning("Google Sheets not configured, skipping position read")
        return []

    try:
        service = _get_service()
        sheet_range = f"{settings.GOOGLE_SHEETS_POSITION_SHEET}!A:E"
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=settings.GOOGLE_SHEETS_SPREADSHEET_ID,
                range=sheet_range,
            )
            .execute()
        )
        rows = result.get("values", [])
        if len(rows) < 2:
            return []

        headers = rows[0]
        positions = []
        for row in rows[1:]:
            # Pad row to match header length
            padded = row + [""] * (len(headers) - len(row))
            pos = {}
            for i, h in enumerate(headers):
                key = _normalize_header(h)
                pos[key] = padded[i]
            # Parse numeric fields
            pos["quantity"] = _safe_float(pos.get("quantity", ""))
            pos["avg_cost"] = _safe_float(pos.get("avg_cost", ""))
            if pos.get("symbol"):
                positions.append(pos)

        return positions
    except Exception as e:
        logger.error(f"Google Sheets position read error: {e}")
        return []


# --- News Archive Sheet ---

async def append_news(articles: list[dict]) -> int:
    """Append articles to the news archive sheet.

    Columns: 資料日期 | 標題 | 分類 | 網址 | 內容
    """
    if not _is_configured() or not articles:
        return 0

    try:
        service = _get_service()
        rows = []
        for a in articles:
            rows.append([
                a.get("published_at") or datetime.utcnow().strftime("%Y-%m-%d"),
                a.get("title", ""),
                a.get("category", ""),
                a.get("source_url", ""),
                (a.get("content", "") or "")[:500],  # Truncate content
            ])

        body = {"values": rows}
        sheet_range = f"{settings.GOOGLE_SHEETS_NEWS_SHEET}!A:E"
        service.spreadsheets().values().append(
            spreadsheetId=settings.GOOGLE_SHEETS_SPREADSHEET_ID,
            range=sheet_range,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()

        return len(rows)
    except Exception as e:
        logger.error(f"Google Sheets news append error: {e}")
        return 0


async def get_saved_news(limit: int = 100) -> list[dict]:
    """Read saved news from the archive sheet."""
    if not _is_configured():
        return []

    try:
        service = _get_service()
        sheet_range = f"{settings.GOOGLE_SHEETS_NEWS_SHEET}!A:E"
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=settings.GOOGLE_SHEETS_SPREADSHEET_ID,
                range=sheet_range,
            )
            .execute()
        )
        rows = result.get("values", [])
        if len(rows) < 2:
            return []

        # Return most recent first (skip header)
        news = []
        for row in reversed(rows[1:]):
            if len(news) >= limit:
                break
            padded = row + [""] * (5 - len(row))
            news.append({
                "published_at": padded[0],
                "title": padded[1],
                "category": padded[2],
                "source_url": padded[3],
                "content": padded[4],
            })
        return news
    except Exception as e:
        logger.error(f"Google Sheets news read error: {e}")
        return []


# --- GAS Web App (no Service Account needed) ---

async def append_news_via_gas(articles: list[dict]) -> bool:
    """Write articles to Google Sheets via GAS Web App endpoint.

    GAS doPost(e) should accept JSON: {action: "appendNews", rows: [...]}
    Each row: {資料日期, 標題, 分類, 網址, 內容}
    """
    if not settings.GOOGLE_APPS_SCRIPT_URL or not articles:
        return False

    rows = []
    for a in articles:
        pub = a.get("published_at") or datetime.utcnow().strftime("%Y-%m-%d")
        if hasattr(pub, "strftime"):
            pub = pub.strftime("%Y-%m-%d")
        rows.append({
            "資料日期": str(pub)[:10],
            "標題": a.get("title", ""),
            "分類": a.get("category", ""),
            "網址": a.get("source_url", ""),
            "內容": (a.get("content", "") or "")[:2000],
        })

    payload = {"action": "appendNews", "rows": rows}
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.post(settings.GOOGLE_APPS_SCRIPT_URL, json=payload)
            if resp.status_code == 200:
                logger.info(f"GAS: appended {len(rows)} rows to Sheets")
                return True
            logger.warning(f"GAS returned status {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"GAS append error: {e}")
        return False


# --- Connection Test ---

async def test_connection() -> dict:
    """Test Google Sheets connection and return status."""
    if not os.path.exists(settings.GOOGLE_SHEETS_CREDENTIALS_FILE):
        return {
            "success": False,
            "message": f"金鑰檔案 {settings.GOOGLE_SHEETS_CREDENTIALS_FILE} 不存在",
        }

    if settings.GOOGLE_SHEETS_SPREADSHEET_ID in _PLACEHOLDER_IDS:
        return {
            "success": False,
            "message": "請在 .env 設定 GOOGLE_SHEETS_SPREADSHEET_ID",
        }

    try:
        service = _get_service()
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=settings.GOOGLE_SHEETS_SPREADSHEET_ID)
            .execute()
        )
        title = meta.get("properties", {}).get("title", "")
        sheets = [s["properties"]["title"] for s in meta.get("sheets", [])]
        return {
            "success": True,
            "message": f"連線成功：{title}",
            "sheet_title": title,
            "tabs": sheets,
        }
    except Exception as e:
        return {"success": False, "message": f"連線失敗：{e}"}


# --- Helpers ---

def _normalize_header(h: str) -> str:
    """Map Chinese/English header names to standard keys."""
    h = h.strip().lower()
    mapping = {
        "symbol": "symbol",
        "名稱": "name",
        "name": "name",
        "數量": "quantity",
        "quantity": "quantity",
        "均價": "avg_cost",
        "avg_cost": "avg_cost",
        "avgcost": "avg_cost",
        "average cost": "avg_cost",
        "類別": "category",
        "category": "category",
    }
    return mapping.get(h, h)


def _safe_float(val) -> float | None:
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None
