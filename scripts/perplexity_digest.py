"""
Perplexity 自動新聞摘要腳本
===============================
功能：每小時抓最新財經新聞 → Perplexity 分析 → 推 LINE

使用方式：
  驗證瀏覽器能正常開啟（首次建議先跑）：
    python scripts/perplexity_digest.py --check

  正常執行（手動測試）：
    python scripts/perplexity_digest.py

  Windows 排程（每小時自動跑）：
    見 scripts/setup_scheduler.bat

注意：
  - 使用你現有的 Chrome（你已登入 Perplexity 的那個），不需額外登入
  - 執行時 Chrome 必須是關閉狀態（或使用獨立的自動化 Profile）
  - 若 Chrome 開著，在 .env 設定 CHROME_PROFILE_DIR 為另一個 Profile 名稱
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# ── 設定（優先讀 .env，沒有就用預設值） ──────────────────────────────────
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

BACKEND_URL        = os.getenv("BACKEND_URL", "http://localhost:8000")
LINE_TOKEN         = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TARGET_ID     = os.getenv("LINE_TARGET_ID", "")
HOURS_BACK         = int(os.getenv("DIGEST_HOURS_BACK", "1"))
MIN_ARTICLES       = int(os.getenv("DIGEST_MIN_ARTICLES", "1"))   # 不足幾篇就跳過

# Chrome profile 設定
# 預設使用系統 Chrome 的 Default profile（你已登入 Perplexity 的那個）
# 若 Chrome 執行中，可在 Chrome 另建一個 Profile 專用於自動化，
# 然後把 Profile 資料夾名稱（如 "Profile 2"）填入 .env 的 CHROME_PROFILE_DIR
_default_chrome_data = str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
CHROME_USER_DATA   = os.getenv("CHROME_USER_DATA_DIR", _default_chrome_data)
CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "Default")

# ── 新聞擷取 ─────────────────────────────────────────────────────────────

def get_recent_articles() -> list[dict]:
    """向後端取近 HOURS_BACK 小時的高/緊急文章。"""
    try:
        resp = requests.get(f"{BACKEND_URL}/api/radar/alerts",
                            params={"limit": 50}, timeout=15)
        resp.raise_for_status()
        alerts = resp.json()
    except Exception as e:
        print(f"[ERROR] 無法取得 alerts：{e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    articles = []

    for alert in alerts:
        raw_dt = alert.get("created_at", "")
        try:
            # 支援 "2026-04-02T14:00:00" 與 "2026-04-02T14:00:00+00:00"
            dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt < cutoff:
            continue

        content = alert.get("content", "")
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            sev_match = re.match(r"^\{(critical|high|medium|low)\}(.*)", line)
            if not sev_match:
                continue
            sev, rest = sev_match.group(1), sev_match.group(2).strip()
            if sev not in ("critical", "high"):
                continue
            # 移除 (關鍵字：...) 後綴
            clean = re.sub(r"\s*\(關鍵字：.+?\)$", "", rest).strip()
            articles.append({"severity": sev, "text": clean})

    return articles


# ── 提示詞組建 ────────────────────────────────────────────────────────────

_SEV_LABEL = {"critical": "🔴 緊急", "high": "🟠 高"}

def build_prompt(articles: list[dict]) -> str:
    critical = [a for a in articles if a["severity"] == "critical"]
    high     = [a for a in articles if a["severity"] == "high"]

    lines = [f"以下是過去 {HOURS_BACK} 小時內偵測到的財經重要新聞，請用繁體中文分析：\n"]

    if critical:
        lines.append("【緊急】")
        for i, a in enumerate(critical, 1):
            lines.append(f"  {i}. {a['text']}")
    if high:
        lines.append("【高重要度】")
        for i, a in enumerate(high, 1):
            lines.append(f"  {i}. {a['text']}")

    lines.append("""
請提供：
1. 最值得關注的 2-3 則新聞及其對台灣市場的潛在影響
2. 整體市場情緒判斷（樂觀 / 謹慎 / 悲觀）
3. 建議關注的後續指標或事件
請簡潔，回覆控制在 400 字以內。""")

    return "\n".join(lines)


# ── Perplexity 瀏覽器自動化 ───────────────────────────────────────────────

def _wait_until_stable(page, selector: str, timeout: int = 90) -> str:
    """等到指定 selector 的文字停止增長（串流完成）。"""
    prev, stable = 0, 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            el = page.query_selector(selector)
            text = el.inner_text() if el else ""
            if len(text) >= 20:
                if len(text) == prev:
                    stable += 1
                    if stable >= 3:   # 連續 6 秒沒變化 → 完成
                        return text
                else:
                    stable = 0
                prev = len(text)
        except Exception:
            pass
    return page.query_selector(selector).inner_text() if page.query_selector(selector) else ""


COOKIES_FILE = Path(__file__).parent / ".perplexity_cookies.json"


def _make_browser_context(p, headless: bool = False):
    """建立 Playwright Chromium context（帶 stealth + cookie）。"""
    browser = p.chromium.launch(headless=headless, slow_mo=80)
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    if COOKIES_FILE.exists():
        cookies = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
        ctx.add_cookies(cookies)
    return browser, ctx


def query_perplexity(prompt: str, check_mode: bool = False, setup_mode: bool = False) -> str | None:
    """Playwright Chromium（內建）開 Perplexity，送出提示詞，回傳回覆文字。"""
    with sync_playwright() as p:
        browser, ctx = _make_browser_context(p, headless=False)
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)   # 隱藏 navigator.webdriver 等自動化特徵

        if setup_mode:
            # 首次設定：讓使用者手動登入（請用 Email 登入，不要用 Google）
            print("\n" + "="*55)
            print("首次設定：請在瀏覽器裡登入 Perplexity")
            print("重要：請用 Email / 密碼 登入，不要按「Sign in with Google」")
            print("      （Google 會擋自動化瀏覽器的 OAuth 流程）")
            print("="*55)
            page.goto("https://www.perplexity.ai/login", wait_until="domcontentloaded", timeout=30000)
            print("\n登入完成後，回到這裡按 Enter 儲存 session...")
            input()
            # 儲存 cookies
            COOKIES_FILE.write_text(
                json.dumps(ctx.cookies(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"[OK] Cookies 已儲存到 {COOKIES_FILE}")
            print("往後執行不需再登入，直接跑 python scripts/perplexity_digest.py")
            browser.close()
            return None

        # 確認是否有 cookies
        if not COOKIES_FILE.exists():
            print("[ERROR] 尚未設定登入 session，請先執行：")
            print("        python scripts/perplexity_digest.py --setup")
            browser.close()
            return None

        print("[INFO] 正在開啟 Perplexity...")
        try:
            page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[WARN] 頁面載入逾時：{e}")
        page.wait_for_timeout(2000)

        if check_mode:
            title = page.title()
            url = page.url
            print(f"[CHECK] 頁面標題：{title}")
            print(f"[CHECK] 目前網址：{url}")
            is_logged_in = "perplexity.ai" in url and "login" not in url
            print(f"[CHECK] 登入狀態：{'✓ 已登入' if is_logged_in else '✗ 未登入，請執行 --setup'}")
            print("[CHECK] 10 秒後自動關閉...")
            page.wait_for_timeout(10000)
            browser.close()
            return None

        # 找輸入框（多個候選 selector 依序嘗試）
        input_selectors = [
            "textarea[placeholder*='Ask']",
            "textarea[placeholder*='ask']",
            "textarea[placeholder*='搜尋']",
            "textarea",
        ]
        textarea = None
        for sel in input_selectors:
            try:
                page.wait_for_selector(sel, timeout=8000)
                textarea = page.query_selector(sel)
                if textarea:
                    break
            except Exception:
                pass

        if not textarea:
            print("[ERROR] 找不到 Perplexity 輸入框，介面可能已更新")
            browser.close()
            return None

        textarea.click()
        page.wait_for_timeout(500)
        textarea.fill(prompt)
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")

        print("[INFO] 等待 Perplexity 回應...")

        # 等回應容器出現（多個候選）
        response_selectors = [
            ".prose",
            "[class*='prose']",
            "[class*='answer']",
            "[class*='response']",
            "div[data-testid*='answer']",
        ]
        response_el = None
        for sel in response_selectors:
            try:
                page.wait_for_selector(sel, timeout=20000)
                response_el = sel
                break
            except Exception:
                pass

        if not response_el:
            print("[WARN] 找不到回應容器，等待 30 秒後直接擷取頁面文字")
            page.wait_for_timeout(30000)
            result = page.inner_text("body")
        else:
            result = _wait_until_stable(page, response_el)

        browser.close()
        return result.strip() if result else None


# ── LINE 推播 ────────────────────────────────────────────────────────────

def push_line(message: str) -> bool:
    if not LINE_TOKEN or not LINE_TARGET_ID:
        print("[SKIP] LINE_TOKEN 或 LINE_TARGET_ID 未設定，跳過推播")
        return False
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {LINE_TOKEN}",
                     "Content-Type": "application/json"},
            json={"to": LINE_TARGET_ID,
                  "messages": [{"type": "text", "text": message[:4990]}]},
            timeout=15,
        )
        if resp.status_code == 200:
            print("[OK] LINE 推播成功")
            return True
        print(f"[ERROR] LINE 推播失敗：{resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[ERROR] LINE 推播例外：{e}")
    return False


# ── 主流程 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true",
                        help="首次使用：開啟瀏覽器讓你用 Email 登入 Perplexity 並儲存 session")
    parser.add_argument("--check", action="store_true",
                        help="測試瀏覽器能否正常開啟並確認 Perplexity 登入狀態")
    args = parser.parse_args()

    if args.setup:
        query_perplexity("", setup_mode=True)
        return

    if args.check:
        query_perplexity("", check_mode=True)
        return

    # 1. 取近期文章
    articles = get_recent_articles()
    print(f"[INFO] 取得 {len(articles)} 篇高/緊急文章（過去 {HOURS_BACK} 小時）")

    if len(articles) < MIN_ARTICLES:
        print(f"[SKIP] 文章數不足 {MIN_ARTICLES} 篇，跳過本次分析")
        return

    # 2. 組提示詞
    prompt = build_prompt(articles)
    print(f"[INFO] 提示詞長度：{len(prompt)} 字元")

    # 3. 查詢 Perplexity
    response = query_perplexity(prompt)
    if not response:
        print("[ERROR] 未取得回應")
        sys.exit(1)

    print("\n── Perplexity 回應 ──────────────────────")
    print(response[:800])
    print("────────────────────────────────────────\n")

    # 4. 推 LINE
    now_str = datetime.now().strftime("%m/%d %H:%M")
    message = f"📊 財經雷達摘要 {now_str}\n\n{response}"
    push_line(message)


if __name__ == "__main__":
    main()
