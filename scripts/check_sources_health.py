#!/usr/bin/env python3
"""
新聞來源健康度檢查腳本
對每個資料來源直接發 HTTP 請求，報告能否抓到文章、最新文章時間距今幾小時。

使用方法：
  python scripts/check_sources_health.py                    # 讀本地 DB
  python scripts/check_sources_health.py http://34.23.154.194  # 從 VM API 取來源清單
  python scripts/check_sources_health.py --active-only       # 只檢查啟用的來源
  python scripts/check_sources_health.py -v                  # 顯示樣本標題

需要套件：pip install httpx feedparser beautifulsoup4 requests
"""

import asyncio
import io
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

# 強制 stdout 使用 UTF-8（避免 Windows CP950 編碼錯誤）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import httpx
    import feedparser
    from bs4 import BeautifulSoup
except ImportError:
    print("請先安裝：pip install httpx feedparser beautifulsoup4")
    sys.exit(1)

LOCAL_DB = Path(__file__).parent.parent / "data" / "financial_radar.db"

# ── 狀態符號（ASCII 相容）─────────────────────────────────────────────────────
OK   = "[OK] "
WARN = "[!!] "
ERR  = "[XX] "
BOLD = ""   # Windows terminal 不支援 ANSI，改用純文字


def _age_str(dt: datetime | None) -> str:
    """將 datetime 轉成「X 小時前」字串。

    無時區資訊的 datetime 視為 UTC+8（台灣時間）後轉換為 UTC 比較。
    """
    if dt is None:
        return "時間未知"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # 台灣媒體 RSS 通常輸出 CST（UTC+8）但不帶時區標記
        from datetime import timezone as tz
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    delta = now - dt
    hours = delta.total_seconds() / 3600
    # 未來時間（排程發布）顯示為「即將」
    if hours < -1:
        return f"未來 {abs(int(hours))}h（排程）"
    if abs(hours) < 1:
        return f"{max(0, int(delta.total_seconds() / 60))} 分鐘前"
    if hours < 48:
        return f"{hours:.1f} 小時前"
    return f"{delta.days} 天前"


def _parse_dt(val) -> datetime | None:
    """嘗試把各種格式的時間字串轉成 datetime。"""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    for fmt in [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(str(val), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


# ── RSS 檢查 ──────────────────────────────────────────────────────────────────

async def check_rss(url: str, timeout: int = 20) -> dict:
    """Fetch RSS feed and return count + newest article info."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SourceChecker/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

        entries = feed.get("entries", [])
        if not entries:
            return {"ok": False, "count": 0, "newest": None, "error": "RSS 回傳 0 則文章"}

        newest = None
        sample_titles = []
        for e in entries[:5]:
            sample_titles.append(e.get("title", "")[:60])
            pub = e.get("published") or e.get("updated") or e.get("pubDate")
            if pub:
                dt = _parse_dt(pub)
                if dt and (newest is None or dt > newest):
                    newest = dt

        # feedparser struct_time
        for e in entries[:5]:
            for key in ("published_parsed", "updated_parsed"):
                t = e.get(key)
                if t:
                    try:
                        import time
                        dt = datetime(*t[:6], tzinfo=timezone.utc)
                        if newest is None or dt > newest:
                            newest = dt
                    except Exception:
                        pass

        return {
            "ok": True,
            "count": len(entries),
            "newest": newest,
            "feed_title": feed.get("feed", {}).get("title", ""),
            "sample_titles": sample_titles,
        }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "count": 0, "newest": None, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "count": 0, "newest": None, "error": str(e)[:80]}


# ── Website / JSON API 檢查 ────────────────────────────────────────────────────

async def check_cnyes(url: str) -> dict:
    """鉅亨網 JSON API。"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://news.cnyes.com/",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        items = (data.get("items") or {}).get("data") or data.get("data") or []
        if not items:
            return {"ok": False, "count": 0, "newest": None, "error": "JSON 無 items"}
        newest = None
        titles = []
        for item in items[:5]:
            titles.append(item.get("title", "")[:60])
            pub = item.get("publishAt") or item.get("created_at")
            if pub:
                try:
                    dt = datetime.fromtimestamp(int(pub), tz=timezone.utc)
                    if newest is None or dt > newest:
                        newest = dt
                except Exception:
                    pass
        return {"ok": True, "count": len(items), "newest": newest, "sample_titles": titles}
    except Exception as e:
        return {"ok": False, "count": 0, "newest": None, "error": str(e)[:80]}


async def check_worldbank(url: str) -> dict:
    """World Bank JSON API。"""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        docs = data.get("documents") or {}
        # API key 格式已從數字改為 hash 字串，改用 isinstance 過濾
        items = [v for v in docs.values() if isinstance(v, dict) and "title" in v]
        if not items:
            return {"ok": False, "count": 0, "newest": None, "error": "JSON 無 documents"}

        def _cdata(v):
            return v["cdata!"] if isinstance(v, dict) else (v or "")

        newest = None
        titles = []
        for item in items[:5]:
            t = item.get("title") or item.get("repnm") or ""
            titles.append(_cdata(t)[:60])
            pub = item.get("lnchdt") or item.get("docdt") or ""
            pub_str = _cdata(pub)
            if pub_str:
                dt = _parse_dt(pub_str[:19])
                if dt and (newest is None or dt > newest):
                    newest = dt
        return {"ok": True, "count": len(items), "newest": newest, "sample_titles": titles}
    except Exception as e:
        return {"ok": False, "count": 0, "newest": None, "error": str(e)[:80]}


async def check_fsc(url: str) -> dict:
    """金管會 HTML 爬蟲。"""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"news_view\.jsp"))
        if not links:
            return {"ok": False, "count": 0, "newest": None, "error": "找不到 news_view.jsp 連結"}
        titles = [a.get_text(strip=True)[:60] for a in links[:5]]
        # FSC 日期從 URL 參數或頁面文字擷取
        date_re = re.compile(r"(\d{3})/(\d{2})/(\d{2})")
        newest = None
        for tag in soup.find_all(string=date_re):
            m = date_re.search(tag)
            if m:
                y = int(m.group(1)) + 1911
                mo, d = int(m.group(2)), int(m.group(3))
                try:
                    dt = datetime(y, mo, d, tzinfo=timezone.utc)
                    if newest is None or dt > newest:
                        newest = dt
                except Exception:
                    pass
        return {"ok": True, "count": len(links), "newest": newest, "sample_titles": titles}
    except Exception as e:
        return {"ok": False, "count": 0, "newest": None, "error": str(e)[:80]}


async def check_caixin(url: str) -> dict:
    """財新 HTML 爬蟲。"""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    date_pattern = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/")
    try:
        async with httpx.AsyncClient(timeout=20, verify=False, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = [a["href"] for a in soup.find_all("a", href=date_pattern) if a.get("href")]
        if not links:
            return {"ok": False, "count": 0, "newest": None, "error": "找不到日期格式連結"}
        newest = None
        titles = []
        for a in soup.find_all("a", href=date_pattern)[:5]:
            titles.append(a.get_text(strip=True)[:60])
            m = date_pattern.search(a["href"])
            if m:
                try:
                    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
                    if newest is None or dt > newest:
                        newest = dt
                except Exception:
                    pass
        return {"ok": True, "count": len(links), "newest": newest, "sample_titles": titles}
    except Exception as e:
        return {"ok": False, "count": 0, "newest": None, "error": str(e)[:80]}


async def check_mops() -> dict:
    """公開資訊觀測站 JSON API。"""
    url = "https://mops.twse.com.tw/mops/api/home_page/t05sr01_1"
    try:
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            resp = await client.post(url, json={"count": 20, "marketKind": "sii"})
            resp.raise_for_status()
            data = resp.json()
        items = data if isinstance(data, list) else data.get("data") or []
        if not items:
            return {"ok": False, "count": 0, "newest": None, "error": "API 回傳空資料"}
        titles = [str(i.get("subject", ""))[:60] for i in items[:5]]
        # 民國日期
        newest = None
        date_re = re.compile(r"(\d+)/(\d+)/(\d+)")
        for item in items[:5]:
            for field in ["time", "date", "announcementDate"]:
                v = str(item.get(field, ""))
                m = date_re.search(v)
                if m:
                    y = int(m.group(1)) + (1911 if int(m.group(1)) < 200 else 0)
                    try:
                        dt = datetime(y, int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
                        if newest is None or dt > newest:
                            newest = dt
                    except Exception:
                        pass
        return {"ok": True, "count": len(items), "newest": newest, "sample_titles": titles}
    except Exception as e:
        return {"ok": False, "count": 0, "newest": None, "error": str(e)[:80]}


# ── 分派 ──────────────────────────────────────────────────────────────────────

async def check_source(src: dict) -> dict:
    """根據 type 和 URL 選擇正確的抓取方法。"""
    t = src["type"]
    url = src["url"] or ""

    if t == "mops":
        return await check_mops()
    if t in ("rss", "social", "person"):
        return await check_rss(url)
    if t == "website":
        if "cnyes.com" in url:
            return await check_cnyes(url)
        if "worldbank.org" in url:
            return await check_worldbank(url)
        if "fsc.gov.tw" in url:
            return await check_fsc(url)
        if "caixinglobal.com" in url:
            return await check_caixin(url)
        # 通用 HTML fallback
        return await check_rss(url)  # try RSS parse first
    return {"ok": False, "count": 0, "newest": None, "error": f"未知類型: {t}"}


# ── 資料載入 ──────────────────────────────────────────────────────────────────

def load_sources_from_db(active_only: bool) -> list[dict]:
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.row_factory = sqlite3.Row
    where = "WHERE is_active=1" if active_only else ""
    rows = conn.execute(
        f"SELECT id, name, type, url, is_active, fetch_all FROM monitor_sources {where} ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_sources_from_api(vm_url: str, active_only: bool) -> list[dict]:
    try:
        import requests
        resp = requests.get(f"{vm_url}/api/settings/sources", timeout=10)
        resp.raise_for_status()
        sources = resp.json()
        if active_only:
            sources = [s for s in sources if s.get("is_active")]
        return sources
    except Exception as e:
        print(f"無法從 VM 取得來源清單：{e}\n改用本地 DB")
        return load_sources_from_db(active_only)


# ── 主程式 ──────────────────────────────────────────────────────────────────

async def main():
    active_only = "--active-only" in sys.argv
    vm_url = next((a for a in sys.argv[1:] if a.startswith("http")), None)

    if vm_url:
        print(f"從 VM API 取得來源清單：{vm_url}")
        sources = load_sources_from_api(vm_url, active_only)
    else:
        print(f"從本地 DB 讀取來源清單")
        sources = load_sources_from_db(active_only)

    # 排除 research 類型（另有研究報告頁面）
    sources = [s for s in sources if s.get("type") != "research"]
    print(f"共 {len(sources)} 個來源{'（僅啟用）' if active_only else '（全部）'}\n")

    print(f"{'狀態':<6} {'來源名稱':<30} {'類型':<8} {'文章數':>5} {'最新文章時間':<16} 備註")
    print("─" * 90)

    ok_count = warn_count = err_count = 0
    STALE_HOURS = 48  # 超過 48h 視為過期警告

    # 逐一檢查（依序，避免同時大量請求被封）
    for src in sources:
        name = (src.get("name") or "")[:28]
        stype = src.get("type") or ""
        active = src.get("is_active", True)
        status_prefix = "" if active else "[停用] "

        result = await check_source(src)
        count = result.get("count", 0)
        newest = result.get("newest")
        error = result.get("error", "")

        if not result["ok"]:
            status = ERR
            age = error[:30] if error else "失敗"
            err_count += 1
        else:
            if newest:
                now = datetime.now(timezone.utc)
                if newest.tzinfo is None:
                    newest = newest.replace(tzinfo=timezone.utc)
                hours_old = (now - newest).total_seconds() / 3600
                if hours_old > STALE_HOURS:
                    status = WARN
                    warn_count += 1
                else:
                    status = OK
                    ok_count += 1
                age = _age_str(newest)
            else:
                status = WARN
                age = "時間未知"
                warn_count += 1

        note = ""
        if result.get("feed_title"):
            note = f"[{result['feed_title'][:25]}]"
        if not active:
            note = "(停用)" + note

        print(f"  {status}   {status_prefix}{name:<28} {stype:<8} {count:>5}   {age:<16} {note}")

        # 印出樣本標題（verbose）
        if "--verbose" in sys.argv or "-v" in sys.argv:
            for t in (result.get("sample_titles") or [])[:3]:
                print(f"         · {t}")

    print("─" * 90)
    print(f"\n結果：[OK] {ok_count} 正常  [!!] {warn_count} 警告  [XX] {err_count} 失敗")
    print(f"\n提示：加 --active-only 只檢查啟用來源，加 -v 顯示樣本標題")
    print(f"      超過 {STALE_HOURS}h 無新文章的來源會標黃色警告")


if __name__ == "__main__":
    asyncio.run(main())
