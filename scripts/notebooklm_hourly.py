#!/usr/bin/env python3
"""
NotebookLM 每小時自動化腳本（本機執行）。

用途：
  每小時從 VM API 抓取緊急新聞與 YouTube 新影片，分別匯入兩個 NotebookLM 筆記本做 AI 深度分析，
  並將結果儲存至本機 nlm_reports/。

前置條件（本機）：
  pip install notebooklm-py requests beautifulsoup4
  notebooklm login   # 首次認證（開啟瀏覽器），認證過期需重新執行

環境變數（複製 .env.local.example 為 .env.local 並填入）：
  API_BASE_URL         VM 的 API 位址，例如 http://34.xx.xx.xx
  NOTEBOOK_ID          新聞分析用 NotebookLM Notebook ID
  NOTEBOOK_ID_YT       YouTube 分析用 NotebookLM Notebook ID（留空則跳過 YT 分析）
  RESULT_PUSH_LINE     true = 同時推播 LINE（需 VM LINE_TARGET_ID 已設定）
  HOURS_BACK           回溯小時數，預設 1（超過此時間未執行時自動補分析）
  MIN_SEVERITY         最低嚴重度（critical / high），預設 high

斷線補分析邏輯：
  腳本將上次執行時間記錄於 .nlm_state.json。
  若距上次執行超過 HOURS_BACK 小時，自動從上次結束點補分析所有遺漏內容。

Windows Task Scheduler 設定：
  動作：wscript D:/即時偵測系統claude/scripts/run_nlm_silent.vbs
  觸發：每小時，從整點開始
  設定：只在連接網路時執行
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# ── 讀取 .env.local ────────────────────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_script_dir, ".env.local")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

API_BASE_URL     = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
NOTEBOOK_ID      = os.environ.get("NOTEBOOK_ID", "")
NOTEBOOK_ID_YT   = os.environ.get("NOTEBOOK_ID_YT", "")
RESULT_PUSH_LINE = os.environ.get("RESULT_PUSH_LINE", "false").lower() == "true"
HOURS_BACK       = int(os.environ.get("HOURS_BACK", "1"))
MIN_SEVERITY     = os.environ.get("MIN_SEVERITY", "high")

_SEV_RANK   = {"critical": 3, "high": 2, "medium": 1, "low": 0}
_STATE_FILE = os.path.join(_script_dir, ".nlm_state.json")


# ══════════════════════════════════════════════════════════════════════════════
# 狀態管理（斷線補分析）
# ══════════════════════════════════════════════════════════════════════════════

def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARNING] 無法儲存狀態：{e}")


def _get_cutoff(state: dict, key: str) -> datetime:
    """
    回傳此次分析的時間起點。
    若距上次執行超過 HOURS_BACK 小時（斷線/關機），從上次執行時間補起；
    否則使用標準 HOURS_BACK 回溯窗口。
    """
    now = datetime.now(timezone.utc)
    last_run_str = state.get(key)
    if last_run_str:
        try:
            last_dt = datetime.fromisoformat(last_run_str)
            gap_hours = (now - last_dt).total_seconds() / 3600
            if gap_hours > HOURS_BACK:
                print(f"  [補分析] 距上次執行 {gap_hours:.1f} 小時，從 {last_dt.strftime('%m/%d %H:%M')} UTC 補起")
                return last_dt
        except Exception:
            pass
    return now - timedelta(hours=HOURS_BACK)


# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════

def _parse_alert_articles(alert: dict) -> list[dict]:
    """解析 Alert.content（{severity} 前綴格式）還原文章清單。"""
    lines = (alert.get("content") or "").splitlines()
    urls_raw_val = alert.get("source_urls") or "[]"
    if isinstance(urls_raw_val, list):
        urls_raw = urls_raw_val
    else:
        try:
            urls_raw = json.loads(urls_raw_val)
        except Exception:
            urls_raw = []

    articles = []
    for i, line in enumerate(lines):
        m = re.match(r'^\{(critical|high|medium|low)\}(.*)', line)
        if not m:
            continue
        raw = m.group(2).strip()
        title = re.sub(r'^\[[^\]]+\]\s*', '', raw)
        title = re.sub(r'\s*[（(]關鍵字[：:].*?[)）]', '', title).strip()
        url = ""
        if i < len(urls_raw):
            raw_url = urls_raw[i]
            url = re.sub(r'^\{[^}]+\}', '', raw_url).strip()
        articles.append({"severity": m.group(1), "title": title, "url": url})
    return articles


def _html_to_text(html: str) -> str:
    """HTML 轉純文字，優先使用 BeautifulSoup，沒有則用 regex。"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        text = re.sub(r'<[^>]+>', ' ', html)
        return re.sub(r'\s+', ' ', text).strip()


async def _cleanup_sources(client, notebook_id: str):
    """清除 notebook 內所有舊 sources（每次從空白開始）。"""
    try:
        existing = await client.sources.list(notebook_id)
        if existing:
            for src in existing:
                await client.sources.delete(notebook_id, src.id)
            print(f"  已刪除 {len(existing)} 個舊 source")
        else:
            print("  無舊 source 需清除")
    except Exception as e:
        print(f"  [WARNING] 清除舊 sources 失敗（非致命）：{e}")


async def _add_source_with_fallback(
    client, notebook_id: str, url: str, title: str, requests_mod
) -> str:
    """
    嘗試以 URL 匯入；若失敗改抓取內文以 text 方式匯入。
    回傳 "url" / "text" / "failed"。
    """
    # Step 1：直接匯入 URL
    try:
        await client.sources.add_url(notebook_id, url=url, wait=False)
        return "url"
    except Exception:
        pass

    # Step 2：抓取內文後以 text 匯入
    try:
        resp = requests_mod.get(
            url, timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            allow_redirects=True,
        )
        text = _html_to_text(resp.text)[:8000]
        content = f"# {title}\n\n來源：{url}\n\n{text}"
        await client.sources.add_text(notebook_id, title=title[:100], content=content, wait=False)
        return "text"
    except Exception:
        return "failed"


# ══════════════════════════════════════════════════════════════════════════════
# 新聞分析
# ══════════════════════════════════════════════════════════════════════════════

def _build_news_summary(alerts: list[dict], cutoff: datetime) -> str:
    """將多則 Alert 整理成 Markdown 摘要 source。"""
    now_tw = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")
    lines = [
        f"# 金融偵測緊急新聞（{now_tw} UTC+8）\n",
        f"**分析時段**：{cutoff.astimezone(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')} 起 | **篩選等級**：{MIN_SEVERITY} 以上\n",
        "---\n",
    ]
    for i, alert in enumerate(alerts, 1):
        sev_label = {"critical": "🚨 緊急", "high": "⚠️ 高風險"}.get(alert.get("severity"), alert.get("severity", ""))
        try:
            dt = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=8))
            ).strftime("%m/%d %H:%M")
        except Exception:
            dt = alert.get("created_at", "")[:16]

        lines.append(f"## 警報 {i}：{alert.get('title', '')[:80]}")
        lines.append(f"**等級**：{sev_label} | **時間**：{dt}\n")
        if alert.get("exposure_summary"):
            lines.append(f"**部位暴險**：{alert['exposure_summary']}\n")

        articles = _parse_alert_articles(alert)
        if articles:
            lines.append("**相關文章**：")
            for a in articles[:15]:
                line = f"- [{a['severity']}] {a['title']}"
                if a["url"]:
                    line += f"\n  {a['url']}"
                lines.append(line)
            lines.append("")
        lines.append("---\n")

    return "\n".join(lines)


async def _run_news_analysis(alerts: list[dict], cutoff: datetime, requests_mod) -> str | None:
    """新聞分析：匯入文章 URL（失敗則抓內文）→ 建立分析師團隊報告。"""
    try:
        from notebooklm import NotebookLMClient
        from notebooklm.rpc.types import ReportFormat
    except ImportError:
        print("[ERROR] 缺少 notebooklm-py 套件", file=sys.stderr)
        return None

    min_rank = _SEV_RANK.get(MIN_SEVERITY, 2)
    article_data: list[dict] = []
    seen_urls: set[str] = set()
    for alert in alerts:
        for a in _parse_alert_articles(alert):
            if _SEV_RANK.get(a["severity"], 0) < min_rank:
                continue
            if a["url"] and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                article_data.append(a)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 新聞：{len(alerts)} 則警報，{len(article_data)} 個文章 URL")

    source_title = f"緊急新聞_{datetime.now().strftime('%Y%m%d_%H%M')}"
    MAX_URLS = 20
    reports_dir = os.path.join(_script_dir, "nlm_reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_file = os.path.join(reports_dir, f"{datetime.now().strftime('%Y%m%d_%H%M')}.md")

    added_url = added_text = skipped = 0
    answer = ""

    try:
        async with await NotebookLMClient.from_storage() as client:

            # Step 0：清除舊 sources
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [新聞] 清除舊 sources...")
            await _cleanup_sources(client, NOTEBOOK_ID)

            # Step A：逐一匯入文章（URL 優先，失敗則抓內文）
            for a in article_data[:MAX_URLS]:
                url = a["url"]
                if "news.google.com" in url:
                    try:
                        r = requests_mod.head(url, allow_redirects=True, timeout=8,
                                              headers={"User-Agent": "Mozilla/5.0"})
                        url = r.url
                    except Exception:
                        pass

                result = await _add_source_with_fallback(client, NOTEBOOK_ID, url, a["title"], requests_mod)
                if result == "url":
                    added_url += 1
                    print(f"  [+URL ] [{a['severity']}] {a['title'][:55]}")
                elif result == "text":
                    added_text += 1
                    print(f"  [+TEXT] [{a['severity']}] {a['title'][:55]}")
                else:
                    skipped += 1
                    print(f"  [skip ] {a['title'][:55]}")

            # Step B：附上警報摘要
            total_added = added_url + added_text
            summary_text = _build_news_summary(alerts, cutoff)
            if total_added == 0:
                print("[WARNING] 所有 URL 均失敗，改以完整文字 source 匯入")
            await client.sources.add_text(NOTEBOOK_ID, title=source_title, content=summary_text, wait=True)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 已匯入 URL:{added_url} 文字:{added_text} 略過:{skipped} + 1份摘要")

            # Step C：建立分析師團隊報告
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 建立新聞分析報告...")
            gen_status = await client.artifacts.generate_report(
                NOTEBOOK_ID,
                report_format=ReportFormat.CUSTOM,
                language="zh-TW",
                custom_prompt=(
                    "你是一個由資深金融分析師組成的研究小組，負責分析本批次匯入的金融新聞。\n\n"
                    "【團隊架構】\n"
                    "• 組長（35 年市場經歷）：宏觀掌握全局，分配任務並負責最終彙整\n"
                    "• 台股分析師：深耕台灣上市櫃、法人動向、半導體供應鏈脈動\n"
                    "• 總經／匯市分析師：專精利率、通膨、各國央行政策與主要貨幣走勢\n"
                    "• 國際市場分析師：覆蓋美歐股市、地緣政治風險、制裁與資金流向\n"
                    "• 商品能源分析師：追蹤油氣、原物料、OPEC 動態與供應鏈影響\n\n"
                    "【執行流程】\n"
                    "1. 組長先將本批新聞依主題分類（例如：地緣政治、央行政策、台股個股、能源商品等）\n"
                    "2. 對應分析師結合數十年市場底蘊與當前時事背景，提出核心觀點\n"
                    "3. 組長考量各市場交叉影響與市場參與者互動行為，彙整輸出最終報告\n\n"
                    "【報告格式要求】\n"
                    "- 新聞類別標題用「一、」「二、」「三、」等中文數字編號\n"
                    "- 每個類別內的分析要點用「1.」「2.」「3.」阿拉伯數字條列，共 3 點\n"
                    "- 每點約 100 字，該類別合計不超過 350 字\n"
                    "- 文字精簡淺白但分析程度要深，必須涵蓋跨市場連動與參與者行為因素\n"
                    "- 報告最末統一列出「來源網址」區塊，完整羅列本次所有分析引用的新聞連結\n"
                    "- 全程使用繁體中文撰寫"
                ),
            )

            # Step D：等待完成
            completed = await client.artifacts.wait_for_completion(
                NOTEBOOK_ID, gen_status.task_id, timeout=300.0
            )
            if completed.is_failed:
                print(f"[ERROR] 新聞報告生成失敗：{completed.error}", file=sys.stderr)
                return None

            # Step E：下載報告
            saved_path = await client.artifacts.download_report(
                NOTEBOOK_ID, output_path=report_file, artifact_id=completed.task_id
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 新聞報告已儲存：{saved_path}")
            with open(saved_path, encoding="utf-8") as f:
                answer = f.read()
            print(f"  共 {len(answer)} 字")

    except ValueError as e:
        if "Authentication expired" in str(e) or "Run 'notebooklm login'" in str(e):
            print("[ERROR] NotebookLM 認證已過期，請在本機執行：notebooklm login", file=sys.stderr)
        else:
            print(f"[ERROR] NotebookLM 失敗：{e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] NotebookLM 失敗：{e}", file=sys.stderr)
        return None

    # Step F：寫回 VM API
    if answer:
        try:
            payload = {
                "content": answer,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "alert_ids": [a.get("id") for a in alerts if a.get("id")],
                "source_title": source_title,
            }
            resp = requests_mod.post(
                f"{API_BASE_URL}/api/radar/notebooklm-report", json=payload, timeout=10
            )
            if resp.status_code in (200, 201):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 新聞分析已寫回 VM API")
        except Exception:
            pass

    return answer


# ══════════════════════════════════════════════════════════════════════════════
# YouTube 分析
# ══════════════════════════════════════════════════════════════════════════════

async def _run_yt_analysis(videos: list[dict], cutoff: datetime, requests_mod) -> str | None:
    """YouTube 影片分析：匯入 YT URL → 建立頻道洞察報告。"""
    if not NOTEBOOK_ID_YT:
        print("[跳過] NOTEBOOK_ID_YT 未設定，略過 YouTube 分析")
        return None

    try:
        from notebooklm import NotebookLMClient
        from notebooklm.rpc.types import ReportFormat
    except ImportError:
        print("[ERROR] 缺少 notebooklm-py 套件", file=sys.stderr)
        return None

    print(f"[{datetime.now().strftime('%H:%M:%S')}] YouTube：{len(videos)} 支影片")

    source_title = f"YT影片_{datetime.now().strftime('%Y%m%d_%H%M')}"
    MAX_VIDEOS = 15
    reports_dir = os.path.join(_script_dir, "nlm_reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_file = os.path.join(reports_dir, f"yt_{datetime.now().strftime('%Y%m%d_%H%M')}.md")

    added = skipped = 0
    answer = ""

    try:
        async with await NotebookLMClient.from_storage() as client:

            # Step 0：清除舊 sources
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [YT] 清除舊 sources...")
            await _cleanup_sources(client, NOTEBOOK_ID_YT)

            # Step A：匯入 YouTube URL（失敗則以標題+簡介 text 補救）
            for v in videos[:MAX_VIDEOS]:
                url = v.get("url", "")
                title = v.get("title", "")
                channel = v.get("channel_name", "")
                if not url:
                    continue

                result = await _add_source_with_fallback(client, NOTEBOOK_ID_YT, url, title, requests_mod)
                if result == "url":
                    added += 1
                    print(f"  [+URL ] [{channel}] {title[:55]}")
                elif result == "text":
                    added += 1
                    print(f"  [+TEXT] [{channel}] {title[:55]}")
                else:
                    skipped += 1
                    print(f"  [skip ] {title[:55]}")

            # Step B：附上影片清單摘要
            now_tw = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")
            since_tw = cutoff.astimezone(timezone(timedelta(hours=8))).strftime("%m/%d %H:%M")
            summary_lines = [
                f"# 金融頻道影片清單（{now_tw} UTC+8）\n",
                f"**分析時段**：{since_tw} 起\n",
                "## 影片清單",
            ]
            for v in videos[:MAX_VIDEOS]:
                pub = ""
                try:
                    pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")).astimezone(
                        timezone(timedelta(hours=8))
                    ).strftime("%m/%d %H:%M")
                except Exception:
                    pass
                summary_lines.append(f"- [{v.get('channel_name','')}] {v.get('title','')} ({pub})")
                if v.get("description"):
                    summary_lines.append(f"  {v['description'][:120]}")
                if v.get("url"):
                    summary_lines.append(f"  {v['url']}")
            await client.sources.add_text(
                NOTEBOOK_ID_YT, title=source_title, content="\n".join(summary_lines), wait=True
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 已匯入 YT URL:{added} 略過:{skipped} + 1份摘要")

            # Step C：建立頻道洞察報告
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 建立 YT 分析報告...")
            gen_status = await client.artifacts.generate_report(
                NOTEBOOK_ID_YT,
                report_format=ReportFormat.CUSTOM,
                language="zh-TW",
                custom_prompt=(
                    "你是一位資深金融媒體研究員，負責分析本批次金融 YouTube 頻道的最新影片內容。\n\n"
                    "【分析任務】\n"
                    "1. 整理各頻道本期關注的主要議題（按重要性排序）\n"
                    "2. 提煉各影片的核心觀點與市場判斷，特別注意與台灣市場相關的看法\n"
                    "3. 歸納各頻道間的共識與分歧，找出市場目前最受關注的焦點\n\n"
                    "【報告格式要求】\n"
                    "- 議題類別標題用「一、」「二、」「三、」等中文數字編號\n"
                    "- 每個類別內的要點用「1.」「2.」「3.」阿拉伯數字條列，共 3 點\n"
                    "- 每點約 100 字，該類別合計不超過 350 字\n"
                    "- 注重跨頻道觀點的整合與比較，找出市場情緒的共同脈絡\n"
                    "- 報告最末統一列出「影片來源」區塊，列出頻道名稱、影片標題與連結\n"
                    "- 全程使用繁體中文撰寫"
                ),
            )

            # Step D：等待完成
            completed = await client.artifacts.wait_for_completion(
                NOTEBOOK_ID_YT, gen_status.task_id, timeout=300.0
            )
            if completed.is_failed:
                print(f"[ERROR] YT 報告生成失敗：{completed.error}", file=sys.stderr)
                return None

            # Step E：下載報告
            saved_path = await client.artifacts.download_report(
                NOTEBOOK_ID_YT, output_path=report_file, artifact_id=completed.task_id
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] YT 報告已儲存：{saved_path}")
            with open(saved_path, encoding="utf-8") as f:
                answer = f.read()
            print(f"  共 {len(answer)} 字")

    except ValueError as e:
        if "Authentication expired" in str(e) or "Run 'notebooklm login'" in str(e):
            print("[ERROR] NotebookLM 認證已過期，請在本機執行：notebooklm login", file=sys.stderr)
        else:
            print(f"[ERROR] NotebookLM YT 失敗：{e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] NotebookLM YT 失敗：{e}", file=sys.stderr)
        return None

    return answer


# ══════════════════════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════════════════════

def main():
    try:
        import requests
    except ImportError:
        print("[ERROR] 缺少 requests 套件，請執行：pip install requests", file=sys.stderr)
        sys.exit(1)

    if not NOTEBOOK_ID:
        print("[ERROR] 請設定環境變數 NOTEBOOK_ID", file=sys.stderr)
        sys.exit(1)

    state = _load_state()
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 新聞分析 ──────────────────────────────────────────────────────────────
    news_cutoff = _get_cutoff(state, "news_last_run")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 抓取新聞警報（自 {news_cutoff.strftime('%m/%d %H:%M')} UTC）...")

    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/radar/alerts",
            params={"type": "news", "limit": 100},
            timeout=15,
        )
        resp.raise_for_status()
        all_alerts = resp.json()
    except Exception as e:
        print(f"[ERROR] 無法連接 API：{e}", file=sys.stderr)
        sys.exit(1)

    min_rank = _SEV_RANK.get(MIN_SEVERITY, 2)
    alerts = []
    for a in all_alerts:
        if _SEV_RANK.get(a.get("severity", ""), 0) < min_rank:
            continue
        try:
            created = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
            if created >= news_cutoff:
                alerts.append(a)
        except Exception:
            pass

    if alerts:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(alerts)} 則警報")
        asyncio.run(_run_news_analysis(alerts, news_cutoff, requests))
        state["news_last_run"] = now_iso
        _save_state(state)
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 無符合條件的新聞警報，跳過")

    # ── YouTube 分析 ──────────────────────────────────────────────────────────
    if not NOTEBOOK_ID_YT:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] NOTEBOOK_ID_YT 未設定，略過 YouTube 分析")
    else:
        yt_cutoff = _get_cutoff(state, "yt_last_run")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 抓取 YouTube 影片（自 {yt_cutoff.strftime('%m/%d %H:%M')} UTC）...")

        try:
            resp = requests.get(
                f"{API_BASE_URL}/api/youtube/videos",
                params={"limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
            all_videos = resp.json()
        except Exception as e:
            print(f"[WARNING] 無法取得 YouTube 影片：{e}")
            all_videos = []

        videos = []
        for v in all_videos:
            try:
                pub = datetime.fromisoformat((v.get("published_at") or "").replace("Z", "+00:00"))
                if pub >= yt_cutoff:
                    videos.append(v)
            except Exception:
                pass

        if videos:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(videos)} 支新影片")
            asyncio.run(_run_yt_analysis(videos, yt_cutoff, requests))
            state["yt_last_run"] = now_iso
            _save_state(state)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 無新 YouTube 影片，跳過")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 全部完成")


if __name__ == "__main__":
    main()
