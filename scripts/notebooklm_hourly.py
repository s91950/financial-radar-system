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
  HOURS_BACK           回溯小時數，預設 3（配合每 3 小時排程；超過此時間未執行時自動補分析）
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
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# Windows 預設 CP950 編碼會在含有 CP950 字集外中文字（如「燈」U+706F）的頻道名稱或影片標題時
# 導致 notebooklm-py 序列化失敗；強制 stdout/stderr 使用 UTF-8 避免此問題。
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ── 日誌設定：同時輸出到 console 和 run.log ──────────────────────────────────
_script_dir_early = os.path.dirname(os.path.abspath(__file__))
_log_dir = os.path.join(_script_dir_early, "nlm_reports")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "run.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_file, encoding="utf-8", mode="a"),
    ],
)
_log = logging.getLogger("nlm")

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
MIN_SEVERITY     = os.environ.get("MIN_SEVERITY", "low")

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
    """HTML 轉純文字，聚焦主文內容，去除導覽列、相關新聞、訂閱 CTA 等雜訊。"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # ① 移除明確雜訊標籤
        for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                          "iframe", "noscript", "figure", "figcaption", "form",
                          "button", "input", "select", "textarea"]):
            tag.decompose()

        # ② 移除常見雜訊 class / id（導覽、相關新聞、廣告、訂閱區塊等）
        _NOISE = [
            "recommend", "related", "more-news", "also-read", "read-more",
            "newsletter", "subscribe", "subscription", "paywall", "register",
            "sidebar", "breadcrumb", "tag-list", "social", "share", "comment",
            "advertisement", "ad-", "banner", "popup", "modal", "promo",
            "hot-news", "popular", "trending", "latest-news",
        ]
        for el in soup.find_all(True):
            cls = " ".join(el.get("class", [])).lower()
            id_ = (el.get("id") or "").lower()
            if any(p in cls or p in id_ for p in _NOISE):
                el.decompose()

        # ③ 優先找語意化主文容器
        content = ""
        for selector in [
            "article",
            "[itemprop='articleBody']",
            ".article-body", ".article-content", ".article__body",
            "#article-content", "#articleBody",
            ".story-body", ".post-content", ".content-body",
            "main",
        ]:
            try:
                el = soup.select_one(selector)
            except Exception:
                continue
            if el:
                content = el.get_text(separator="\n", strip=True)
                break

        # ④ 退而求其次：只收 <p> 段落，過濾過短的（導覽 / 按鈕文字）
        if not content:
            paras = [p.get_text(strip=True) for p in soup.find_all("p")]
            paras = [p for p in paras if len(p) > 25]
            content = "\n\n".join(paras)

        # ⑤ 最後手段：整頁純文字
        if not content:
            content = soup.get_text(separator="\n", strip=True)

        # 去除連續空白行，限制長度
        lines = [ln.strip() for ln in content.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)

    except ImportError:
        text = re.sub(r'<[^>]+>', ' ', html)
        return re.sub(r'\s+', ' ', text).strip()


_SKILLS_DIR = os.path.join(_script_dir, "skills")
_SKILL_PREFIX = "[SKILL] "


async def _ensure_skill_sources(client, notebook_id: str):
    """確保 NLM notebook 內的 [SKILL] sources 與 skills/ 目錄完全同步：
    - skills/ 有但 NLM 沒有 → 補匯入
    - NLM 有但 skills/ 已刪除 → 從 NLM 移除（孤兒清理）
    """
    if not os.path.isdir(_SKILLS_DIR):
        print(f"  [Skills] 找不到 skills/ 目錄（{_SKILLS_DIR}），跳過")
        return

    skill_files = sorted(f for f in os.listdir(_SKILLS_DIR) if f.lower().endswith(".md"))
    if not skill_files:
        print("  [Skills] skills/ 目錄內無 .md 檔，跳過")
        return

    # 以 skills/ 內的檔案為基準，建立預期標題集合
    expected_titles = {
        f"{_SKILL_PREFIX}{os.path.splitext(f)[0]}" for f in skill_files
    }

    try:
        existing = await client.sources.list(notebook_id)
        existing_skill_sources = {
            s.title: s for s in existing
            if s.title and s.title.startswith(_SKILL_PREFIX)
        }
    except Exception as e:
        print(f"  [Skills] 無法取得現有 sources：{e}")
        existing_skill_sources = {}

    # 移除孤兒（NLM 有、skills/ 已不存在）
    removed = 0
    for title, src in existing_skill_sources.items():
        if title not in expected_titles:
            try:
                await client.sources.delete(notebook_id, src.id)
                removed += 1
                print(f"  [Skills] 移除孤兒：{title}")
            except Exception as e:
                print(f"  [Skills] 移除失敗 {title}：{e}")

    # 補匯入缺少的 skill
    added = skipped = 0
    for filename in skill_files:
        title = f"{_SKILL_PREFIX}{os.path.splitext(filename)[0]}"
        if title in existing_skill_sources:
            skipped += 1
            continue
        filepath = os.path.join(_SKILLS_DIR, filename)
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            await client.sources.add_text(notebook_id, title=title, content=content, wait=False)
            added += 1
            print(f"  [Skills] 匯入：{filename}")
        except Exception as e:
            print(f"  [Skills] 匯入失敗 {filename}：{e}")

    parts = []
    if added:
        parts.append(f"新增 {added}")
    if removed:
        parts.append(f"移除 {removed}")
    if not parts:
        parts.append("已同步")
    print(f"  [Skills] 完成（{', '.join(parts)}，目前 {len(skill_files)} 個 skill 檔）")


async def _cleanup_news_sources(client, notebook_id: str):
    """清除 notebook 內的新聞 / YT sources，保留 [SKILL] 開頭的永久 sources。"""
    try:
        existing = await client.sources.list(notebook_id)
        to_delete = [s for s in existing if not (s.title or "").startswith(_SKILL_PREFIX)]
        skill_count = len(existing) - len(to_delete)
        if to_delete:
            for src in to_delete:
                await client.sources.delete(notebook_id, src.id)
            print(f"  已刪除 {len(to_delete)} 個新聞 sources（保留 {skill_count} 個 skill sources）")
        else:
            print(f"  無新聞 sources 需清除（保留 {skill_count} 個 skill sources）")
    except Exception as e:
        print(f"  [WARNING] 清除新聞 sources 失敗（非致命）：{e}")


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
        text = _html_to_text(resp.text)

        # 品質門檻：純文字去除空白後 < 100 字視為無效（導覽頁、空頁、403 頁面等）
        if len(text.replace(" ", "").replace("\n", "")) < 100:
            return "failed"

        # 截取前 6000 字（主文通常在前段，避免帶入頁尾相關新聞）
        content = f"# {title}\n\n來源：{url}\n\n{text[:6000]}"
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
        lines.append("")
    return "\n".join(lines)


def _build_news_prompt_v1(article_count: int) -> str:
    """
    【舊版 v1 備份，已暫停使用】
    依文章數量選擇分析提示詞版本，使用 PROJECT_INSTRUCTIONS_v2 + SKILL_* 框架。
    輸出格式：最多 2 個主題類別，每類固定 3 點（事件描述／市場影響／後續分析）。
    """
    team_preamble = (
        "你是由多名頂尖金融專業人士組成的分析團隊，團隊架構、各分析師專業底蘊、"
        "六層分析流程及全體禁止行為，詳見已上傳的 [SKILL] PROJECT_INSTRUCTIONS_v2 "
        "與各 [SKILL] SKILL_* 檔案，請以這些檔案作為分析框架與視角依據。\n\n"
        "分析時必須：\n"
        "• 由最適合的分析師角色主導（宏觀/債市/股市/匯率/商品/地緣政治等），"
        "並以跨角色視角交叉驗證\n"
        "• 每個觀察點追蹤至少三層因果鏈（直接影響 → 市場反應 → 結構性影響）\n"
        "• 點出不同市場參與者的立場分歧（外資、央行、散戶至少涵蓋一組）\n"
        "• 若有反證條件（「若___發生，此判斷不成立」），請在相關段落中標示\n\n"
    )
    source_rule = (
        "【來源規則】\n"
        "• 只能根據本次實際匯入的新聞來源進行分析，禁止引用或虛構任何未匯入的文章\n"
        "• 若匯入來源不足以支撐某個論點，請縮短篇幅，不可用自身知識庫填補\n\n"
    )
    output_format = (
        "【報告格式（嚴格遵守）】\n\n"
        "第一行為報告主標題（H1），點出本批次核心主題，例如：\n"
        "# 金融新聞深度分析：[核心主題關鍵字]\n\n"
        "報告主體分為最多 2 個主題類別（若文章高度集中同一主題，可只有 1 個類別）。\n"
        "類別由你根據本批次新聞的核心主軸決定，選出最重要的 1～{max_cat} 個主題。\n\n"
        "每個類別格式如下：\n\n"
        "### 一、 [類別名稱]：[子標題，一句話點出核心事件或趨勢]\n\n"
        "1. **事件描述**：（約 100 字）完整描述該類別的核心事件：發生了什麼、"
        "關鍵人物言論、當前狀態為何。\n\n"
        "2. **市場與國別影響**：（約 100 字）哪些市場（股、債、匯、商品）與國家受到衝擊，"
        "各方參與者（外資、央行、企業、散戶）如何反應，資金流向為何。\n\n"
        "3. **後續分析**：（約 100 字）此事件下一步最可能的走向，跨市場連動意涵，"
        "對投資人的行動意涵，並標示反證條件：「若___發生，此判斷不成立」。\n\n"
        "---\n\n"
        "報告最末統一列出「### 關鍵來源」區塊，每類別每點各列 1 篇最關鍵來源：\n"
        "格式：- 一-1. 標題（URL）\n"
        "      - 一-2. 標題（URL）\n"
        "      - 一-3. 標題（URL）\n"
        "      - 二-1. 標題（URL）（若有第二類別）\n"
        "每篇文章優先作為一個點的來源；若已被引用，改引次關鍵來源。\n"
        "只列確實匯入的文章，禁止虛構，若來源無可用 URL 則標示「（來源文本）」。\n\n"
        "全程使用繁體中文撰寫。"
    )
    if article_count < 10:
        fmt = output_format.replace("{max_cat}", "1")
    else:
        fmt = output_format.replace("{max_cat}", "2")
    return team_preamble + source_rule + fmt


def _build_news_prompt(article_count: int) -> str:
    """
    【新版 v2】基於「定期市場新聞分析簡報 ─ 分析師合議版」SKILL 框架。
    完整規範（五大類別、三段式結構、分析師池、企業機構清單、品質清單）
    詳見已上傳的 [SKILL] 新聞分析SKILL 文件。

    < 10 篇 → 精簡版：選出最重要的 1 個類別
    ≥ 10 篇 → 分類版：選出最重要的 1～3 個類別
    """
    max_cat = "1" if article_count < 10 else "3"

    return (
        "你是一個「定期市場新聞分析簡報」系統。"
        "完整的分析框架（核心運作邏輯、分析師合議召集機制、三段式結構規範、"
        "企業機構參考清單、輸出模板、品質清單、分類判斷準則與常見錯誤範例）"
        "全部詳見已上傳的 [SKILL] 新聞分析SKILL 文件，請嚴格遵照該文件執行。\n\n"
        "【本次執行指示】\n"
        f"本批次共 {article_count} 篇新聞。"
        f"請從五大類別（總經/央行政策、台股/亞股、信用市場/私募信貸、"
        f"FX/大宗商品/地緣政治、財金總經綜合）中，"
        f"選出最重要的 1～{max_cat} 個有料類別進行分析；無料類別直接省略，不得硬湊。\n"
        "涵蓋時段請根據匯入的新聞摘要 source 中「分析時段」欄位自動填入。\n\n"
        "【三段式格式提醒（[SKILL] 新聞分析SKILL 第三節）】\n"
        "每個類別固定輸出三點，對應：\n"
        "① 事件 + 市場反應（What + How，含具體數據、幅度、時序）\n"
        "② 分析師合議解讀（Why it matters，必須點名具體公司/機構，"
        "呈現跨市場/跨國別傳導路徑，禁止「金融股」「科技股」等模糊詞）\n"
        "③ 後續觀察（What to watch，具體可驗證的追蹤項目，含時間/數字/明確關卡，"
        "禁止「持續觀察」「值得關注」等空話）\n\n"
        "【來源標注規則】\n"
        "• 每點結尾附 1-2 則核心新聞網址，格式：[1][2]\n"
        "• 報告末尾統一列出【關鍵新聞來源】區塊，格式：[1] https://...\n"
        "• 同一網址全份報告只出現一次，不得重複引用\n"
        "• 只能根據本次實際匯入的新聞來源進行分析，禁止引用或虛構未匯入的文章\n\n"
        "全程使用繁體中文撰寫。"
    )


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

            # Step 0：確保 skill sources 存在，再清除舊新聞 sources
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [新聞] 確認 skill sources...")
            await _ensure_skill_sources(client, NOTEBOOK_ID)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [新聞] 清除舊新聞 sources...")
            await _cleanup_news_sources(client, NOTEBOOK_ID)

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

            # Step C：建立分析師團隊報告（依文章數量選擇提示詞版本）
            prompt_version = "分類版(≤3類)" if len(articles) >= 10 else "精簡版(1類)"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 建立新聞分析報告（v2 新聞分析SKILL，{prompt_version}，共 {len(articles)} 篇）...")
            gen_status = await client.artifacts.generate_report(
                NOTEBOOK_ID,
                report_format=ReportFormat.CUSTOM,
                language="zh-TW",
                custom_prompt=_build_news_prompt(len(articles)),
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

            # Step 0：確保 skill sources 存在，再清除舊 YT sources
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [YT] 確認 skill sources...")
            await _ensure_skill_sources(client, NOTEBOOK_ID_YT)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [YT] 清除舊影片 sources...")
            await _cleanup_news_sources(client, NOTEBOOK_ID_YT)

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
                if v.get("url"):
                    summary_lines.append(f"  {v['url']}")
            await client.sources.add_text(
                NOTEBOOK_ID_YT, title=source_title, content="\n".join(summary_lines), wait=True
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 已匯入 YT URL:{added} 略過:{skipped} + 1份摘要")

            # Step C：建立頻道洞察報告
            # ── YT 提示詞 v1（舊版備份，已暫停使用） ──────────────────────────
            # _YT_PROMPT_V1 = (
            #     "你是由多名頂尖金融專業人士組成的分析團隊，團隊架構、各分析師專業底蘊、"
            #     "六層分析流程及全體禁止行為，詳見已上傳的 [SKILL] PROJECT_INSTRUCTIONS_v2 "
            #     "與各 [SKILL] SKILL_* 檔案，請以這些檔案作為分析框架與視角依據。\n\n"
            #     "【執行方式】\n"
            #     "• 由首席分析師（CHIEF-01）為每支影片指派最適合的分析師角色\n"
            #     "• 各分析師依其專業（宏觀/債市/股市/匯率/商品/地緣政治等）提出核心洞察\n"
            #     "• 每個洞察追蹤至少三層因果鏈，並點出跨市場連動與投資人行為因素\n"
            #     "• 若有反證條件（「若___發生，此判斷不成立」），請在相關要點中標示\n\n"
            #     "【來源規則】\n"
            #     "• 只能根據本次實際匯入的影片內容進行分析，禁止引用或虛構未匯入的影片\n\n"
            #     "【報告格式要求（嚴格遵守）】\n"
            #     "- 每支影片獨立一個段落，標題格式：「一、【頻道名稱】影片標題」（依影片清單順序編號）\n"
            #     "- 影片清單中標注 [Shorts] 的影片：只列「1.」共 1 個分析要點（約 60～80 字）\n"
            #     "- 未標注 [Shorts] 的一般影片：列「1.」「2.」「3.」共 3 個分析要點，每點約 80～100 字\n"
            #     "- 文字精簡淺白但分析程度要深，必須涵蓋跨市場連動與投資人行為因素\n"
            #     "- 報告最末統一列出「影片來源」區塊；只列本次確實匯入的影片，"
            #     "格式「一. 【頻道名稱】標題（URL）」，不得引用未在本批次中出現的影片，切勿省略此區塊\n"
            #     "- 全程使用繁體中文撰寫"
            # )
            # ── YT 提示詞 v2（新版，使用 新聞分析SKILL 框架） ──────────────────
            _yt_prompt_v2 = (
                "你是一個「YouTube 金融影片定期簡報」系統。"
                "分析師合議框架（分析師角色池、四層思考、用詞紀律等）"
                "詳見已上傳的 [SKILL] 新聞分析SKILL 文件，請以該文件的分析視角與深度標準執行。\n\n"
                "【本次 YouTube 影片分析格式（嚴格遵守）】\n"
                "• 每支影片獨立一個段落，標題格式：「一、【頻道名稱】影片標題」（依清單順序編號）\n"
                "• [Shorts] 標注的影片：只列「①」共 1 個分析點（約 60-80 字），"
                "必須點名至少一個具體公司或機構\n"
                "• 一般影片：列「①②③」共 3 個分析點，對應：\n"
                "  ① 內容摘要 + 市場訊號（What：影片主張、關鍵數據、觀點方向）\n"
                "  ② 分析師合議解讀（Why：跨市場傳導路徑、具體點名公司/機構、"
                "參與者行為邏輯；禁止「金融股」「科技股」等模糊詞）\n"
                "  ③ 後續觀察（Watch：具體可驗證項目、價格關卡、時間節點；"
                "禁止「持續觀察」「值得關注」等空話）\n"
                "  每點約 80-100 字\n"
                "• 來源規則：只能分析本次匯入的影片，禁止引用未匯入的內容\n"
                "• 報告末尾統一列出「影片來源」區塊，"
                "格式「一. 【頻道名稱】標題（URL）」，不得省略此區塊\n"
                "• 全程使用繁體中文撰寫"
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 建立 YT 分析報告（v2 新聞分析SKILL 框架）...")
            gen_status = await client.artifacts.generate_report(
                NOTEBOOK_ID_YT,
                report_format=ReportFormat.CUSTOM,
                language="zh-TW",
                custom_prompt=_yt_prompt_v2,
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
    改為在獨立 daemon 執行緒中執行，避免背景排程時瀏覽器行為不可預期
    導致主執行緒卡死（subprocess.TimeoutExpired 在某些 Windows 狀態下不會正常觸發）。
    硬性上限 30 秒後強制放棄，不影響後續流程。
    """
    import subprocess, shutil, threading

    # 先檢查 storage_state.json 是否存在且未過期
    state_path = os.path.expanduser("~/.notebooklm/storage_state.json")
    if os.path.exists(state_path):
        age_hours = (datetime.now().timestamp() - os.path.getmtime(state_path)) / 3600
        if age_hours < 12:
            _log.info("NotebookLM 認證檔 %.1f 小時前更新，跳過自動登入", age_hours)
            return

    nlm_bin = shutil.which("notebooklm")
    if not nlm_bin:
        import sysconfig
        scripts = sysconfig.get_path("scripts")
        candidate = os.path.join(scripts, "notebooklm.exe" if sys.platform == "win32" else "notebooklm")
        nlm_bin = candidate if os.path.exists(candidate) else None
    if not nlm_bin:
        _log.warning("找不到 notebooklm 執行檔，跳過自動登入")
        return

    login_result = {"ok": False, "err": ""}

    def _do_login():
        try:
            r = subprocess.run(
                [nlm_bin, "login"],
                input=b"\n",
                timeout=25,
                capture_output=True,
            )
            login_result["ok"] = r.returncode == 0
            if r.returncode != 0:
                login_result["err"] = r.stderr.decode("utf-8", errors="replace")[:200]
        except subprocess.TimeoutExpired:
            login_result["err"] = "timeout"
        except Exception as e:
            login_result["err"] = str(e)[:200]

    _log.info("自動刷新 NotebookLM 認證（執行緒，上限 30s）...")
    t = threading.Thread(target=_do_login, daemon=True)
    t.start()
    t.join(timeout=30)
    if t.is_alive():
        _log.warning("notebooklm login 執行緒逾時（30s），繼續執行")
    elif login_result["ok"]:
        _log.info("NotebookLM 認證已刷新")
    else:
        _log.warning("notebooklm login 非正常結束：%s", login_result["err"])


async def _run_all_async(
    run_news: bool,
    articles: list,
    news_cutoff: "datetime",
    run_yt: bool,
    videos: list,
    yt_cutoff: "datetime",
    requests_mod,
    global_timeout: int = 1500,  # 25 分鐘硬性上限
) -> tuple:
    """
    新聞 + YT 分析合併為單一 event loop 執行，解決 Windows asyncio 二次啟動問題。
    同時加上全域逾時保護，任一步驟 hang 最多 25 分鐘後強制結束。
    """
    async def _inner():
        news_result = None
        yt_result = None
        if run_news and articles:
            news_result = await _run_news_analysis(articles, news_cutoff, requests_mod)
        if run_yt and videos:
            yt_result = await _run_yt_analysis(videos, yt_cutoff, requests_mod)
        return news_result, yt_result

    try:
        return await asyncio.wait_for(_inner(), timeout=global_timeout)
    except asyncio.TimeoutError:
        mins = global_timeout // 60
        print(f"[ERROR] 整體執行逾時（{mins} 分鐘上限），強制結束", file=sys.stderr)
        return None, None


def main():
    _log.info("=" * 60)
    _log.info("NotebookLM 金融分析腳本啟動")
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

    # ── Windows asyncio 穩定性：改用 SelectorEventLoop ──────────────────────
    # ProactorEventLoop（Windows 預設）在 notebooklm-py WebSocket 清理時容易 hang；
    # SelectorEventLoop 更穩定，且 notebooklm-py 不依賴 ProactorEventLoop 功能。
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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

    # ── 同步階段：抓取新聞與 YT 資料 ──────────────────────────────────────────
    # （API 呼叫是同步的，在進入 asyncio 之前先完成，避免混用 sync/async requests）

    articles: list = []
    news_cutoff: datetime = now
    run_news = not args.yt_only

    if run_news:
        news_cutoff = _resolve_cutoff("news_last_run")
        tw_str = news_cutoff.astimezone(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')
        label = "[手動] " if manual_override else ""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {label}抓取新聞文章（自 {tw_str} 台灣時間，嚴重度 {MIN_SEVERITY}+）...")

        _crit_kws = {"崩盤","暴跌","暴漲","危機","緊急","衝擊","崩潰","戰爭","制裁","封鎖","違約","破產"}
        _high_kws = {"下跌","上漲","升息","降息","通膨","衰退","波動","警告","風險","貶值","升值",
                     "利率","匯率","油價","黃金","股市","台積","輝達","聯準"}
        min_sev = MIN_SEVERITY

        def _article_severity(title: str) -> str:
            if any(k in title for k in _crit_kws):
                return "critical"
            if any(k in title for k in _high_kws):
                return "high"
            return "low"

        def _effective_sev(a: dict) -> str:
            db_sev = a.get("severity")
            if db_sev in ("critical", "high", "low"):
                return db_sev
            return _article_severity(a.get("title", ""))

        try:
            resp = requests.get(
                f"{API_BASE_URL}/api/news/articles",
                params={"limit": 500, "fetched_after": news_cutoff.isoformat()},
                timeout=20,
            )
            resp.raise_for_status()
            all_articles = resp.json().get("articles", [])
        except Exception as e:
            print(f"[ERROR] 無法連接 API：{e}", file=sys.stderr)
            sys.exit(1)

        for a in all_articles:
            sev = _effective_sev(a)
            if min_sev == "critical" and sev != "critical":
                continue
            if min_sev == "high" and sev == "low":
                continue
            articles.append(a)

        _AUTO_HIGH_THRESHOLD = 120
        if len(articles) > _AUTO_HIGH_THRESHOLD:
            articles_high = [a for a in articles if _effective_sev(a) in ("critical", "high")]
            print(
                f"  [自動篩選] 文章數 {len(articles)} 篇超過門檻 {_AUTO_HIGH_THRESHOLD}，"
                f"縮減至 high 以上共 {len(articles_high)} 篇"
            )
            articles = articles_high

        if articles:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(articles)} 篇文章")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 無符合條件的新聞文章，跳過新聞分析")
            run_news = False

    videos: list = []
    yt_cutoff: datetime = now
    run_yt = not args.news_only and bool(NOTEBOOK_ID_YT)

    if run_yt:
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

        for v in all_videos:
            ts_str = v.get("published_at") or ""
            if not ts_str:
                videos.append(v)
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= yt_cutoff:
                    videos.append(v)
            except Exception:
                videos.append(v)

        if videos:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(videos)} 支新影片")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 無新 YouTube 影片，跳過 YT 分析")
            run_yt = False

    # ── 非同步階段：單一 asyncio.run()，含全域 25 分鐘逾時保護 ──────────────
    # 兩次 asyncio.run() 會在 Windows 上造成 event loop 二次啟動問題，合併為一次。
    if run_news or run_yt:
        news_result, yt_result = asyncio.run(
            _run_all_async(
                run_news=run_news, articles=articles, news_cutoff=news_cutoff,
                run_yt=run_yt,   videos=videos,   yt_cutoff=yt_cutoff,
                requests_mod=requests,
            )
        )
    else:
        news_result, yt_result = None, None

    # ── 狀態儲存 ──────────────────────────────────────────────────────────────
    if args.no_save_state:
        print("  [--no-save-state] 不更新 state，排程時間記錄保持不變")
    elif not manual_override:
        if run_news:
            state["news_last_run"] = now_iso
        if run_yt:
            state["yt_last_run"] = now_iso
        if run_news or run_yt:
            _save_state(state)

    _log.info("全部完成")
    _log.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log.exception("腳本異常終止：%s", e)
        sys.exit(1)
