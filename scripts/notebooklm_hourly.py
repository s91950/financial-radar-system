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
  觸發：每 3 小時，從 09:00 開始（09:00 / 12:00 / 15:00 / 18:00 / 21:00 / 00:00 / 03:00 / 06:00）
  設定：只在連接網路時執行
"""

import asyncio
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# Windows 預設 CP950 編碼會在含有 CP950 字集外中文字（如「燈」U+706F）的頻道名稱或影片標題時
# 導致 notebooklm-py 序列化失敗；強制 stdout/stderr 使用 UTF-8 避免此問題。
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

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

def _build_news_summary(articles: list[dict], cutoff: datetime) -> str:
    """將文章清單整理成 Markdown 摘要 source（直接來自 Article 資料表）。"""
    now_tw = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")
    since_tw = cutoff.astimezone(timezone(timedelta(hours=8))).strftime("%m/%d %H:%M")
    lines = [
        f"# 金融偵測新聞摘要（{now_tw} UTC+8）\n",
        f"**分析時段**：{since_tw} 起 | **篩選等級**：{MIN_SEVERITY} 以上 | **共 {len(articles)} 篇**\n",
        "---\n",
    ]
    for i, a in enumerate(articles, 1):
        try:
            dt = datetime.fromisoformat((a.get("fetched_at") or "").replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=8))
            ).strftime("%m/%d %H:%M")
        except Exception:
            dt = ""
        lines.append(f"### {i}. {a.get('title', '')}")
        lines.append(f"**來源**：{a.get('source', '')} | **入庫**：{dt}")
        if a.get("source_url"):
            lines.append(f"**連結**：{a['source_url']}")
        if a.get("content"):
            lines.append(f"\n{a['content'][:300]}")
        lines.append("")
    return "\n".join(lines)


async def _run_news_analysis(articles: list[dict], cutoff: datetime, requests_mod) -> str | None:
    """新聞分析：匯入文章 URL（失敗則抓內文）→ 建立分析師團隊報告。
    articles: 直接來自 /api/news/articles 的 Article dict 清單。
    """
    try:
        from notebooklm import NotebookLMClient
        from notebooklm.rpc.types import ReportFormat
    except ImportError:
        print("[ERROR] 缺少 notebooklm-py 套件", file=sys.stderr)
        return None

    # 去重（相同 URL 只保留一篇）
    seen_urls: set[str] = set()
    article_data: list[dict] = []
    for a in articles:
        url = a.get("source_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            article_data.append({"title": a.get("title", ""), "url": url, "source": a.get("source", "")})

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 新聞：{len(articles)} 篇文章，{len(article_data)} 個唯一 URL（全部嘗試匯入）")

    source_title = f"金融新聞_{datetime.now().strftime('%Y%m%d_%H%M')}"
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

            # Step A：逐一匯入所有文章（URL 優先，例外才用抓內文的 text 備援），不設上限
            for a in article_data:
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
                    print(f"  [+URL ] [{a.get('source','')}] {a['title'][:55]}")
                elif result == "text":
                    added_text += 1
                    print(f"  [+TEXT] [{a.get('source','')}] {a['title'][:55]}")
                else:
                    skipped += 1
                    print(f"  [skip ] {a['title'][:55]}")

            # Step B：附上文章摘要（含超出 MAX_URLS 的文章完整列表）
            total_added = added_url + added_text
            summary_text = _build_news_summary(articles, cutoff)
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
                    "• 總經分析師：專精利率、通膨、各國央行政策與全球資金循環\n"
                    "• 地緣政治分析師：專精地緣政治風險、制裁、外交關係對市場的結構性影響\n"
                    "• 國際市場分析師：覆蓋美歐股市、匯市走勢與跨市場資金流向\n"
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
                    "- 報告最末統一列出「關鍵來源」區塊；只能引用本次確實匯入、你確實看到內容的新聞，不得虛構或引用未在本批次中出現的來源；每個分析要點標注最相關的 1 篇，格式「一-1. 標題（URL）」，同一篇新聞若同時支撐多個要點可重複出現（一-1 與 二-2 可相同），不必強求每條都不同，切勿省略此區塊\n"
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
                "alert_ids": [],
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

def _is_youtube_short(video_id: str, requests_mod) -> bool:
    """
    判斷影片是否為 YouTube Shorts（片長通常不到 2 分鐘）。
    原理：對 /shorts/{id} 發送 HEAD 請求（不跟蹤重定向）：
      - 200 → 是 Short（YouTube 不轉址）
      - 3xx → 一般影片（YouTube 轉址到 /watch?v=...）
    逾時或例外時保守返回 False（不過濾）。
    """
    try:
        resp = requests_mod.head(
            f"https://www.youtube.com/shorts/{video_id}",
            allow_redirects=False,
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return resp.status_code == 200
    except Exception:
        return False


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

    print(f"[{datetime.now().strftime('%H:%M:%S')}] YouTube：{len(videos)} 支影片（偵測 Shorts 中...）")

    # 偵測 Shorts（片長不到 2 分鐘）：HEAD /shorts/{id} 回 200 → 是 Short，標記後仍保留分析
    shorts_ids: set[str] = set()
    for v in videos:
        vid_id = v.get("video_id") or ""
        if not vid_id:
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v.get("url", "") or "")
            if m:
                vid_id = m.group(1)
        if vid_id and _is_youtube_short(vid_id, requests_mod):
            shorts_ids.add(vid_id)
            print(f"  [Shorts] {v.get('title', '')[:60]}")
    if shorts_ids:
        print(f"  偵測到 {len(shorts_ids)} 支 Shorts（列入分析，僅寫 1 點）")

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
                # 標記 Shorts
                vid_id = v.get("video_id") or ""
                if not vid_id:
                    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v.get("url", "") or "")
                    if m:
                        vid_id = m.group(1)
                short_tag = " [Shorts]" if vid_id in shorts_ids else ""
                summary_lines.append(f"- [{v.get('channel_name','')}] {v.get('title','')}{short_tag} ({pub})")
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
                    "你是一個由資深金融分析師組成的研究小組，負責解析本批次金融 YouTube 頻道的最新影片內容。\n\n"
                    "【團隊架構】\n"
                    "• 組長（35 年市場經歷）：宏觀掌握全局，分配任務並負責最終彙整\n"
                    "• 台股分析師：深耕台灣上市櫃、法人動向、半導體供應鏈脈動\n"
                    "• 總經分析師：專精利率、通膨、各國央行政策與全球資金循環\n"
                    "• 地緣政治分析師：專精地緣政治風險、制裁、外交關係對市場的結構性影響\n"
                    "• 國際市場分析師：覆蓋美歐股市、匯市走勢與跨市場資金流向\n"
                    "• 商品能源分析師：追蹤油氣、原物料、OPEC 動態與供應鏈影響\n\n"
                    "【執行流程】\n"
                    "1. 組長為每支影片指派最適合的分析師\n"
                    "2. 分析師結合數十年市場底蘊，針對該影片提出核心洞察（一般影片 3 點，Shorts 1 點）\n"
                    "3. 每個洞察須點出市場意涵或對投資人的實際影響\n\n"
                    "【報告格式要求】\n"
                    "- 每支影片獨立一個段落，標題格式：「一、【頻道名稱】影片標題」（依影片清單順序編號）\n"
                    "- 影片清單中標注 [Shorts] 的影片：只列「1.」共 1 個分析要點（約 60～80 字）\n"
                    "- 未標注 [Shorts] 的一般影片：列「1.」「2.」「3.」共 3 個分析要點，每點約 80～100 字\n"
                    "- 文字精簡淺白但分析程度要深，必須涵蓋跨市場連動與投資人行為因素\n"
                    "- 報告最末統一列出「影片來源」區塊；只列本次確實匯入的影片，格式「一. 【頻道名稱】標題（URL）」，不得引用未在本批次中出現的影片，切勿省略此區塊\n"
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

    # Step F：寫回 VM API（供 LINE yt分析 指令使用）
    if answer:
        try:
            payload = {
                "content": answer,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_title": source_title,
            }
            resp = requests_mod.post(
                f"{API_BASE_URL}/api/radar/notebooklm-yt-report", json=payload, timeout=10
            )
            if resp.status_code in (200, 201):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] YT 分析已寫回 VM API")
        except Exception:
            pass

    return answer


# ══════════════════════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════════════════════

def _auto_login():
    """
    執行 notebooklm login 並自動按 Enter。
    - 認證有效：瀏覽器載入 NLM 首頁後自動送出換行，無需人工介入。
    - 認證過期：瀏覽器開啟真正登入畫面，換行會立即送出（太早），
      此時腳本會在後面的 API 呼叫失敗並提示手動執行 notebooklm login。
    - 逾時（30 秒）或找不到 notebooklm 執行檔時，靜默略過不影響後續流程。
    """
    import subprocess, shutil
    nlm_bin = shutil.which("notebooklm")
    if not nlm_bin:
        # 嘗試 Python Scripts 目錄
        import sysconfig
        scripts = sysconfig.get_path("scripts")
        candidate = os.path.join(scripts, "notebooklm.exe" if sys.platform == "win32" else "notebooklm")
        nlm_bin = candidate if os.path.exists(candidate) else None
    if not nlm_bin:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [WARNING] 找不到 notebooklm 執行檔，跳過自動登入")
        return
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 自動刷新 NotebookLM 認證...")
        subprocess.run(
            [nlm_bin, "login"],
            input=b"\n",       # 模擬按 Enter（認證有效時瀏覽器載完即自動繼續）
            timeout=30,
            capture_output=True,
        )
        print(f"[{datetime.now().strftime('%H:%M:%S')}] NotebookLM 認證已刷新")
    except subprocess.TimeoutExpired:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [WARNING] notebooklm login 逾時（30s），略過")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [WARNING] notebooklm login 失敗（非致命）：{e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="NotebookLM 金融分析腳本（手動執行時可覆蓋時間範圍）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python notebooklm_hourly.py                    # 標準排程執行（依 state 補分析）
  python notebooklm_hourly.py --hours 6          # 分析最近 6 小時
  python notebooklm_hourly.py --since "04/15 09:00"  # 從指定時間點起（台灣時間）
  python notebooklm_hourly.py --hours 3 --news-only  # 只跑新聞，最近 3 小時
  python notebooklm_hourly.py --severity critical    # 只分析緊急警報
  python notebooklm_hourly.py --hours 2 --no-save-state  # 補看不影響自動排程狀態
        """,
    )
    parser.add_argument("--hours", type=float, default=None,
                        help="回溯小時數（覆蓋 .env.local 的 HOURS_BACK 與 state 補分析邏輯）")
    parser.add_argument("--since", type=str, default=None,
                        help='分析起始時間，台灣時間格式 "MM/DD HH:MM"，例如 "04/15 09:00"')
    parser.add_argument("--severity", choices=["critical", "high"], default=None,
                        help="覆蓋最低嚴重度門檻（critical / high）")
    parser.add_argument("--news-only", action="store_true", help="只執行新聞分析，跳過 YT")
    parser.add_argument("--yt-only", action="store_true", help="只執行 YT 分析，跳過新聞")
    parser.add_argument("--no-save-state", action="store_true",
                        help="執行完不更新 state（手動補看時不影響自動排程的時間記錄）")
    args = parser.parse_args()

    # 套用 CLI 覆蓋
    global MIN_SEVERITY
    if args.severity:
        MIN_SEVERITY = args.severity

    try:
        import requests
    except ImportError:
        print("[ERROR] 缺少 requests 套件，請執行：pip install requests", file=sys.stderr)
        sys.exit(1)

    if not NOTEBOOK_ID:
        print("[ERROR] 請設定環境變數 NOTEBOOK_ID", file=sys.stderr)
        sys.exit(1)

    # ── 自動刷新 NotebookLM 認證 ──────────────────────────────────────────────
    _auto_login()

    # ── 決定時間起點 ──────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    state = _load_state()
    now_iso = now.isoformat()

    def _resolve_cutoff(state_key: str) -> datetime:
        """根據 CLI 參數決定此次分析起點，優先序：--since > --hours > state 補分析。"""
        if args.since:
            try:
                tw = timezone(timedelta(hours=8))
                dt = datetime.strptime(f"{now.year}/{args.since}", "%Y/%m/%d %H:%M")
                return dt.replace(tzinfo=tw).astimezone(timezone.utc)
            except ValueError:
                print(f"[ERROR] --since 格式錯誤，請用 MM/DD HH:MM，例如 04/15 09:00", file=sys.stderr)
                sys.exit(1)
        if args.hours is not None:
            return now - timedelta(hours=args.hours)
        return _get_cutoff(state, state_key)

    manual_override = args.hours is not None or args.since is not None

    # ── 新聞分析 ──────────────────────────────────────────────────────────────
    if args.yt_only:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] --yt-only：跳過新聞分析")
    else:
        news_cutoff = _resolve_cutoff("news_last_run")
        tw_str = news_cutoff.astimezone(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')
        label = "[手動] " if manual_override else ""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {label}抓取新聞文章（自 {tw_str} 台灣時間，嚴重度 {MIN_SEVERITY}+）...")

        # 直接從 Article 資料表抓取，用 fetched_at 過濾（比 Alerts 完整）
        try:
            resp = requests.get(
                f"{API_BASE_URL}/api/news/articles",
                params={"limit": 300, "include_radar": "true"},
                timeout=20,
            )
            resp.raise_for_status()
            all_articles = resp.json().get("articles", [])
        except Exception as e:
            print(f"[ERROR] 無法連接 API：{e}", file=sys.stderr)
            sys.exit(1)

        # 用 fetched_at 過濾時間窗（入庫時間，非發布時間）
        _crit_kws = {"崩盤","暴跌","暴漲","危機","緊急","衝擊","崩潰","戰爭","制裁","封鎖","違約","破產"}
        _high_kws = {"下跌","上漲","升息","降息","通膨","衰退","波動","警告","風險","貶值","升值",
                     "利率","匯率","油價","黃金","股市","台積","輝達","聯準"}
        min_sev = MIN_SEVERITY

        def _article_severity(title: str) -> str:
            t = title
            if any(k in t for k in _crit_kws):
                return "critical"
            if any(k in t for k in _high_kws):
                return "high"
            return "low"

        articles = []
        for a in all_articles:
            fetched = a.get("fetched_at")
            if not fetched:
                continue
            try:
                ft = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
                if ft.tzinfo is None:
                    ft = ft.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if ft < news_cutoff:
                continue
            sev = _article_severity(a.get("title", ""))
            if min_sev == "critical" and sev != "critical":
                continue
            if min_sev == "high" and sev == "low":
                continue
            articles.append(a)

        if articles:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(articles)} 篇文章")
            asyncio.run(_run_news_analysis(articles, news_cutoff, requests))
            if not args.no_save_state and not manual_override:
                state["news_last_run"] = now_iso
                _save_state(state)
            elif args.no_save_state:
                print("  [--no-save-state] 不更新 state，排程時間記錄保持不變")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 無符合條件的新聞文章，跳過")

    # ── YouTube 分析 ──────────────────────────────────────────────────────────
    if args.news_only:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] --news-only：跳過 YouTube 分析")
    elif not NOTEBOOK_ID_YT:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] NOTEBOOK_ID_YT 未設定，略過 YouTube 分析")
    else:
        yt_cutoff = _resolve_cutoff("yt_last_run")
        if manual_override:
            tw_str = yt_cutoff.astimezone(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [手動] 抓取 YouTube 影片（自 {tw_str} 台灣時間）...")
        else:
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
        if manual_override:
            # 手動指定時間：用 published_at（YouTube 原始上傳時間）過濾，忽略 is_new 狀態
            for v in all_videos:
                try:
                    ts_str = v.get("published_at") or ""
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= yt_cutoff:
                        videos.append(v)
                except Exception:
                    pass
        else:
            # 自動排程：is_new=True 且 published_at 在時間窗口內（yt_cutoff 由 state 決定）
            for v in all_videos:
                if not v.get("is_new"):
                    continue
                ts_str = v.get("published_at") or ""
                if not ts_str:
                    videos.append(v)  # 無發布時間則納入（不遺漏）
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= yt_cutoff:
                        videos.append(v)
                except Exception:
                    videos.append(v)  # 解析失敗則納入（不遺漏）

        if videos:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(videos)} 支新影片")
            asyncio.run(_run_yt_analysis(videos, yt_cutoff, requests))
            if not args.no_save_state and not manual_override:
                state["yt_last_run"] = now_iso
                _save_state(state)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 無新 YouTube 影片，跳過")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 全部完成")


if __name__ == "__main__":
    main()
