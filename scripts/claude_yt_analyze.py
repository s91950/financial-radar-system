#!/usr/bin/env python
"""Claude Code 自動 YouTube 分析 — 資料抓取 / 推送 helper。

設計：Claude Code 在 /loop 迴圈中每隔數小時呼叫本腳本。**分析本身由 Claude Code
（模型推理）完成**，不接 Gemini / Claude API；本腳本只負責兩件雜事：

  fetch  — 從 VM 抓「系統偵測到的新影片」(is_new=True)，去掉本機 state 已分析過的，
           以 JSON 印出待分析清單（給 Claude 讀）。沒有新影片就印 {"videos": []}。
  push   — 把 Claude 寫好的分析報告 POST 回 VM（extension-report, kind=yt，顯示在
           「分析結果 → 🧩 Extension YT」），成功後把這批 video_id 記進 state 檔去重。

state 檔：scripts/.claude_yt_state.json — 只存最近 500 個已分析的 YouTube video_id。
設定來源：scripts/.env.local 的 API_BASE_URL 與 API_TOKEN（service key, admin）。

用法：
  python scripts/claude_yt_analyze.py fetch [--limit 50]
  python scripts/claude_yt_analyze.py push --file report.md --ids id1,id2,... [--title "..."]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# Windows 主控台預設 cp950，含中文標題的 JSON 會 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_STATE_PATH = _HERE / ".claude_yt_state.json"
_ENV_PATH = _HERE / ".env.local"
_MAX_STATE_IDS = 500


def _load_env() -> dict:
    """極簡 .env 解析（不依賴 python-dotenv）。"""
    env = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # 環境變數覆蓋
    for k in ("API_BASE_URL", "API_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _base_and_headers(env: dict):
    base = (env.get("API_BASE_URL") or "").rstrip("/")
    token = env.get("API_TOKEN") or ""
    if not base:
        sys.exit("錯誤：scripts/.env.local 缺 API_BASE_URL")
    headers = {"X-API-Key": token} if token else {}
    return base, headers


def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"analyzed_ids": [], "last_push_at": None}


def _save_state(state: dict) -> None:
    state["analyzed_ids"] = state.get("analyzed_ids", [])[-_MAX_STATE_IDS:]
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_fetch(args) -> None:
    env = _load_env()
    base, headers = _base_and_headers(env)
    state = _load_state()
    analyzed = set(state.get("analyzed_ids", []))

    try:
        r = requests.get(
            f"{base}/api/youtube/videos",
            params={"new_only": "true", "limit": args.limit},
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        videos = r.json() or []
    except Exception as e:
        print(json.dumps({"error": f"抓取失敗：{e}", "videos": []}, ensure_ascii=False))
        return

    pending = []
    for v in videos:
        vid = v.get("video_id") or v.get("youtube_id") or str(v.get("id"))
        if not vid or vid in analyzed:
            continue
        desc = (v.get("description") or "").strip()
        pending.append({
            "video_id": vid,
            "title": v.get("title"),
            "channel": v.get("channel_name") or v.get("channel_title") or v.get("channel"),
            "url": v.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None),
            "published_at": v.get("published_at"),
            "description": desc[:500] if desc else "",
        })

    print(json.dumps({"count": len(pending), "videos": pending}, ensure_ascii=False, indent=2))


def cmd_push(args) -> None:
    env = _load_env()
    base, headers = _base_and_headers(env)

    content = Path(args.file).read_text(encoding="utf-8")
    if not content.strip():
        sys.exit("錯誤：報告檔內容為空，拒絕推送")

    ids = [s for s in (args.ids or "").split(",") if s.strip()]
    title = args.title or f"Claude Code 自動分析（{len(ids)} 部影片）"
    payload = {
        "content": content,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_title": title,
        "notebook_kind": "yt",
    }
    try:
        r = requests.post(
            f"{base}/api/radar/extension-report",
            json=payload,
            headers={**headers, "Content-Type": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
    except Exception as e:
        sys.exit(f"推送失敗：{e}")

    # 推送成功 → 記錄已分析 id 去重
    state = _load_state()
    seen = set(state.get("analyzed_ids", []))
    for vid in ids:
        if vid not in seen:
            state["analyzed_ids"].append(vid)
            seen.add(vid)
    state["last_push_at"] = payload["generated_at"]
    _save_state(state)
    print(f"已推送：{title}；state 已記錄 {len(ids)} 個 video_id（去重用）")


def main() -> None:
    p = argparse.ArgumentParser(description="Claude Code 自動 YouTube 分析 helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="抓取待分析的新影片（JSON）")
    pf.add_argument("--limit", type=int, default=50)
    pf.set_defaults(func=cmd_fetch)

    pp = sub.add_parser("push", help="推送 Claude 寫好的分析報告回系統")
    pp.add_argument("--file", required=True, help="報告 Markdown 檔路徑")
    pp.add_argument("--ids", default="", help="本批分析的 video_id（逗號分隔，去重用）")
    pp.add_argument("--title", default="", help="來源批次標題")
    pp.set_defaults(func=cmd_push)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
