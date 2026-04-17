#!/usr/bin/env python3
"""
NotebookLM 每小時自動化腳本（本機執行）。

用途：
  每小時從 VM 的 API 抓取緊急新聞，自動匯入 NotebookLM 做 AI 深度分析，
  並將分析結果寫回 VM API 供 Web Dashboard 查看。

前置條件（本機）：
  pip install notebooklm-py requests
  notebooklm login   # 首次認證（開啟瀏覽器），後續自動維持（若過期需重新執行）

環境變數（複製 .env.local.example 為 .env.local 並填入）：
  API_BASE_URL         VM 的 API 位址，例如 http://34.xx.xx.xx:8000
  NOTEBOOK_ID          目標 NotebookLM Notebook ID
  RESULT_PUSH_LINE     true = 同時推播 LINE（需 VM LINE_TARGET_ID 已設定）
  HOURS_BACK           回溯小時數，預設 1
  MIN_SEVERITY         最低嚴重度（critical / high），預設 critical

Windows Task Scheduler 設定：
  動作：python D:/即時偵測系統claude/scripts/notebooklm_hourly.py
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

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
NOTEBOOK_ID  = os.environ.get("NOTEBOOK_ID", "")
RESULT_PUSH_LINE = os.environ.get("RESULT_PUSH_LINE", "false").lower() == "true"
HOURS_BACK   = int(os.environ.get("HOURS_BACK", "1"))
MIN_SEVERITY = os.environ.get("MIN_SEVERITY", "critical")

_SEV_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _parse_alert_articles(alert: dict) -> list[dict]:
    """解析 Alert.content（{severity} 前綴格式）還原文章清單。"""
    lines = (alert.get("content") or "").splitlines()
    # source_urls 可能是 JSON 字串（本機讀 DB）或已解析的 list（API 回傳）
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
        # 移除來源前綴 [XXX] 和關鍵字後綴
        title = re.sub(r'^\[[^\]]+\]\s*', '', raw)
        title = re.sub(r'\s*[（(]關鍵字[：:].*?[)）]', '', title).strip()
        url = ""
        if i < len(urls_raw):
            raw_url = urls_raw[i]
            url = re.sub(r'^\{[^}]+\}', '', raw_url).strip()
        articles.append({"severity": m.group(1), "title": title, "url": url})
    return articles


def _build_notebook_content(alerts: list[dict]) -> str:
    """將多則 Alert 整理成 Markdown，作為 NotebookLM 的 source。"""
    now_tw = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")
    lines = [
        f"# 金融偵測緊急新聞（{now_tw} UTC+8）\n",
        f"**回溯時間**：過去 {HOURS_BACK} 小時內 | **篩選等級**：{MIN_SEVERITY} 以上\n",
        "---\n",
    ]
    for i, alert in enumerate(alerts, 1):
        sev_label = {"critical": "🚨 緊急", "high": "⚠️ 高風險"}.get(alert.get("severity"), alert.get("severity", ""))
        dt_str = alert.get("created_at", "")
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=8))
            ).strftime("%m/%d %H:%M")
        except Exception:
            dt = dt_str[:16]

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


async def _run_notebooklm(alerts: list[dict], content_md: str, requests_mod) -> str | None:
    """匯入 NotebookLM，使用「建立報告」功能生成分析，並下載報告。

    流程：
    1. add_url() 匯入達門檻嚴重度的文章連結（Google News URL 先解析重導向）
    2. add_text() 附上警報概覽摘要
    3. artifacts.generate_report() 建立自訂分析報告
    4. wait_for_completion() 等待生成完成
    5. download_report() 下載報告存至 nlm_reports/
    """
    try:
        from notebooklm import NotebookLMClient
        from notebooklm.rpc.types import ReportFormat
    except ImportError:
        print("[ERROR] 缺少 notebooklm-py 套件，請執行：pip install notebooklm-py", file=sys.stderr)
        print("        首次使用需執行：notebooklm login", file=sys.stderr)
        return None

    # ── 收集達到 MIN_SEVERITY 門檻的文章 URL（逐篇判斷，非整個警報）────────
    min_rank = _SEV_RANK.get(MIN_SEVERITY, 3)
    article_data: list[dict] = []
    seen_urls: set[str] = set()
    for alert in alerts:
        for a in _parse_alert_articles(alert):
            if _SEV_RANK.get(a["severity"], 0) < min_rank:
                continue
            if a["url"] and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                article_data.append(a)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 從 {len(alerts)} 則警報提取到 {len(article_data)} 個 {MIN_SEVERITY}+ 文章 URL")
    if article_data:
        print(f"  URL 範例：{article_data[0]['url'][:80]}")

    source_title = f"緊急新聞_{datetime.now().strftime('%Y%m%d_%H%M')}"
    MAX_URLS = 20

    # 準備輸出路徑（先決定，讓 download_report 直接寫入目標位置）
    reports_dir = os.path.join(_script_dir, "nlm_reports")
    os.makedirs(reports_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    report_file = os.path.join(reports_dir, f"{timestamp}.md")

    added_urls = 0
    skipped: list[dict] = []
    answer = ""

    try:
        async with await NotebookLMClient.from_storage() as client:

            # ── Step 0：清除 notebook 內所有舊 sources（每次從空白開始）────────
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 清除舊 sources...")
            try:
                existing_sources = await client.sources.list(NOTEBOOK_ID)
                if existing_sources:
                    for _src in existing_sources:
                        await client.sources.delete(NOTEBOOK_ID, _src.id)
                    print(f"  已刪除 {len(existing_sources)} 個舊 source")
                else:
                    print("  無舊 source 需清除")
            except Exception as _del_err:
                print(f"  [WARNING] 清除舊 sources 失敗（非致命）：{_del_err}")

            # ── Step A：逐一匯入文章 URL ─────────────────────────────────────
            for a in article_data[:MAX_URLS]:
                url = a["url"]
                # Google News RSS 重導向 → 先解析成實際文章 URL
                if "news.google.com" in url:
                    try:
                        r = requests_mod.head(url, allow_redirects=True, timeout=8,
                                              headers={"User-Agent": "Mozilla/5.0"})
                        url = r.url
                    except Exception:
                        pass
                try:
                    await client.sources.add_url(NOTEBOOK_ID, url=url, wait=False)
                    added_urls += 1
                    print(f"  [+URL] [{a['severity']}] {a['title'][:60]}")
                except Exception as e:
                    skipped.append(a)
                    print(f"  [skip] {a['title'][:50]}: {e}")

            # ── Step B：附上警報摘要文字 source ──────────────────────────────
            if added_urls > 0:
                summary_lines = [
                    f"# 本次匯入摘要（{datetime.now().strftime('%Y/%m/%d %H:%M')}）\n",
                    f"已匯入 {added_urls} 篇文章連結，回溯 {HOURS_BACK} 小時、嚴重度 {MIN_SEVERITY}+。\n",
                    "## 警報列表",
                ]
                for alert in alerts:
                    sev = alert.get("severity", "")
                    summary_lines.append(f"- [{sev}] {alert.get('title', '')[:80]}")
                    if alert.get("exposure_summary"):
                        summary_lines.append(f"  部位暴險：{alert['exposure_summary']}")
                if skipped:
                    summary_lines.append(f"\n（另有 {len(skipped)} 篇 URL 無法存取略過）")
                    for a in skipped:
                        summary_lines.append(f"  - [{a['severity']}] {a['title']}")
                summary_text = "\n".join(summary_lines)
            else:
                print("[WARNING] 所有 URL 均無法加入，改用完整文字 source")
                summary_text = content_md

            await client.sources.add_text(
                NOTEBOOK_ID, title=source_title, content=summary_text, wait=True
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 已匯入 {added_urls} 個 URL + 1 份摘要 source")

            # ── Step C：建立報告（分析師團隊框架，繁體中文金融分析）──────────
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 建立報告中...")
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
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 報告生成中（task={gen_status.task_id[:16]}...）")

            # ── Step D：等待報告生成完成（最多 5 分鐘）───────────────────────
            completed = await client.artifacts.wait_for_completion(
                NOTEBOOK_ID, gen_status.task_id, timeout=300.0
            )
            if completed.is_failed:
                print(f"[ERROR] 報告生成失敗：{completed.error}", file=sys.stderr)
                return None
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 報告生成完成，開始下載...")

            # ── Step E：下載報告至 nlm_reports/ ─────────────────────────────
            saved_path = await client.artifacts.download_report(
                NOTEBOOK_ID,
                output_path=report_file,
                artifact_id=completed.task_id,
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 報告已儲存至：{saved_path}")

            with open(saved_path, encoding="utf-8") as f:
                answer = f.read()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 報告共 {len(answer)} 字")

    except ValueError as e:
        if "Authentication expired" in str(e) or "Run 'notebooklm login'" in str(e):
            print("[ERROR] NotebookLM 認證已過期，請在本機執行：notebooklm login", file=sys.stderr)
        else:
            print(f"[ERROR] NotebookLM 失敗：{e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] NotebookLM 失敗：{e}", file=sys.stderr)
        return None

    # ── Step F：寫回 VM API（選用，供 Web Dashboard 顯示）────────────────────
    if answer:
        try:
            alert_ids = [a.get("id") for a in alerts if a.get("id")]
            payload = {
                "content": answer,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "alert_ids": alert_ids,
                "source_title": source_title,
            }
            write_resp = requests_mod.post(
                f"{API_BASE_URL}/api/radar/notebooklm-report",
                json=payload,
                timeout=10,
            )
            if write_resp.status_code in (200, 201):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 分析結果已寫回 VM API")
            elif write_resp.status_code == 404:
                pass
            else:
                print(f"[WARNING] 寫回 API 回傳 {write_resp.status_code}")
        except Exception:
            pass

    return answer


def main():
    try:
        import requests
    except ImportError:
        print("[ERROR] 缺少 requests 套件，請執行：pip install requests", file=sys.stderr)
        sys.exit(1)

    if not NOTEBOOK_ID:
        print("[ERROR] 請設定環境變數 NOTEBOOK_ID", file=sys.stderr)
        sys.exit(1)

    # ── Step 1：從 VM API 抓取緊急警報 ──────────────────────────────────────
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 從 {API_BASE_URL} 抓取警報...")
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/radar/alerts",
            params={"type": "news", "limit": 50},
            timeout=15,
        )
        resp.raise_for_status()
        all_alerts = resp.json()
    except Exception as e:
        print(f"[ERROR] 無法連接 API：{e}", file=sys.stderr)
        sys.exit(1)

    # 過濾：最近 HOURS_BACK 小時 + 嚴重度門檻
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    min_rank = _SEV_RANK.get(MIN_SEVERITY, 3)
    alerts = []
    for a in all_alerts:
        sev_rank = _SEV_RANK.get(a.get("severity", ""), 0)
        if sev_rank < min_rank:
            continue
        try:
            created = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
            if created < cutoff:
                continue
        except Exception:
            pass
        alerts.append(a)

    if not alerts:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 過去 {HOURS_BACK} 小時內無 {MIN_SEVERITY}+ 警報，跳過")
        sys.exit(0)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 找到 {len(alerts)} 則警報，準備匯入 NotebookLM...")

    # ── Step 2：整理 Markdown 內容 ──────────────────────────────────────────
    content_md = _build_notebook_content(alerts)

    # ── Step 3-5：NotebookLM（async） ────────────────────────────────────────
    asyncio.run(_run_notebooklm(alerts, content_md, requests))

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 完成")


if __name__ == "__main__":
    main()
