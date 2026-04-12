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
    urls_raw = []
    try:
        urls_raw = json.loads(alert.get("source_urls") or "[]")
    except Exception:
        pass

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
    """匯入 NotebookLM 並取得分析結果（async）。"""
    try:
        from notebooklm import NotebookLMClient
    except ImportError:
        print("[ERROR] 缺少 notebooklm-py 套件，請執行：pip install notebooklm-py", file=sys.stderr)
        print("        首次使用需執行：notebooklm login", file=sys.stderr)
        return None

    source_title = f"緊急新聞_{datetime.now().strftime('%Y%m%d_%H%M')}"

    try:
        async with await NotebookLMClient.from_storage() as client:
            # ── Step 3：新增文字 source ──────────────────────────────────────
            src = await client.sources.add_text(
                NOTEBOOK_ID, title=source_title, content=content_md, wait=True
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 已匯入 source：{source_title} (id={src.id})")

            # ── Step 4：觸發問答 ─────────────────────────────────────────────
            question = (
                "請分析本小時最重要的金融風險事件，說明：\n"
                "1. 事件摘要（2-3句）\n"
                "2. 對台灣銀行業/金融市場的潛在影響\n"
                "3. 建議關注的後續指標\n"
                "請用繁體中文回答，格式適合在 LINE 閱讀。"
            )
            ask_result = await client.chat.ask(NOTEBOOK_ID, question)
            answer = ask_result.answer if hasattr(ask_result, "answer") else str(ask_result)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] NotebookLM 分析完成（{len(answer)} 字）")
    except ValueError as e:
        if "Authentication expired" in str(e) or "Run 'notebooklm login'" in str(e):
            print(f"[ERROR] NotebookLM 認證已過期，請在本機執行：notebooklm login", file=sys.stderr)
        else:
            print(f"[ERROR] NotebookLM 失敗：{e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] NotebookLM 失敗：{e}", file=sys.stderr)
        return None

    # ── Step 5：儲存分析結果 ────────────────────────────────────────────────
    if answer:
        # 5a. 存至本機 scripts/nlm_reports/（永遠執行）
        reports_dir = os.path.join(_script_dir, "nlm_reports")
        os.makedirs(reports_dir, exist_ok=True)
        report_file = os.path.join(reports_dir, f"{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"來源：{source_title}\n生成時間：{datetime.now().strftime('%Y/%m/%d %H:%M')}\n\n")
            f.write(answer)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 分析結果已存至：{report_file}")

        # 5b. 寫回 VM API（選用，供 Web Dashboard 顯示）
        try:
            alert_ids = [a.get("id") for a in alerts if a.get("id")]
            payload = {
                "content": answer,
                "generated_at": datetime.utcnow().isoformat(),
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
                pass  # 端點尚未實作，靜默略過
            else:
                print(f"[WARNING] 寫回 API 回傳 {write_resp.status_code}")
        except Exception as e:
            pass  # API 不通時不影響本機儲存

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
