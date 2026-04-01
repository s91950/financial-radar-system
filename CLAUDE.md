# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

金融即時偵測系統 (Financial Real-time Detection System) — a multi-module system for monitoring financial markets, aggregating news, tracking research papers, and matching position exposure. Built for senior financial analysts who need real-time alerts via LINE/Email/Web with event summaries, position exposure, and source links.

**Language:** All UI text and comments are in Traditional Chinese (繁體中文). AI analysis output should also be in Traditional Chinese.

## Deployment (Production)

The system runs on **Google Cloud e2-micro VM** (us-east1-d, always free). Production stack:

```
Internet → nginx (:80) → React static (frontend/dist/)
                       → FastAPI (:8000, via proxy)
                       → WebSocket (/ws)

LINE Webhook → Cloudflare Tunnel (HTTPS) → nginx → /api/line/webhook
```

- **Backend service**: `systemd` unit `financial-radar.service`, auto-starts on boot
- **Cloudflare Tunnel**: `systemd` unit `cloudflared.service`, provides HTTPS for LINE webhook (trycloudflare.com URL changes on VM reboot)
- **Deploy scripts**: `deploy/` — `setup.sh`, `deploy.sh`, `financial-radar.service`, `nginx.conf`
- **DB path on VM**: must use absolute path `sqlite:////opt/financial-radar/data/financial_radar.db` in `.env` (relative path fails under systemd)
- **Service user**: VM username is `s9195000409898` (not `ubuntu`) — service file `User=` must match

### Update Production After Code Changes
```bash
# Local
git add . && git commit -m "..." && git push

# On VM (SSH)
cd /opt/financial-radar && git pull
sudo systemctl restart financial-radar
# Frontend changes also require:
cd frontend && npm run build && sudo systemctl restart financial-radar
```

## Commands

### Backend (FastAPI + Python 3.10+)
```bash
# Install dependencies
pip install -r backend/requirements.txt

# Start dev server (from project root)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Health check
curl http://localhost:8000/api/health

# Restart in background (bash)
pkill -f "uvicorn backend.main:app"; sleep 1
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
```

### Frontend (React 18 + Vite 6)
```bash
cd frontend
npm install
npm run dev      # Dev server on :5173, proxies /api and /ws to :8000
npm run build    # Production build to dist/
```

### Both (convenience scripts)
```bash
./start.sh       # Linux/Mac
start.bat        # Windows
```

## Architecture

```
Frontend (:5173) → Vite proxy → FastAPI Backend (:8000)
                                  ├── REST API (/api/*)
                                  ├── WebSocket (/ws) — real-time broadcasting
                                  └── APScheduler — 4 background jobs
```

`vite.config.js` also whitelists `*.ngrok-free.app` / `*.ngrok-free.dev` hosts for remote tunnelling.

### Modules (6 pages)

1. **即時雷達 (Radar)** `/` — Auto-scans RSS + Google News every 5min, creates alerts with position exposure. AI analysis is **on-demand only** (user clicks button) to save API costs.
2. **主題追蹤 (Topics)** `/search` — User-defined topics with boolean keywords. Radar auto-imports matching articles AND merges them into radar alerts.
3. **新聞資料庫 (News DB)** `/news` — Fetch returns a **preview** (not auto-saved). User selects which articles to save to SQLite + Google Sheets. Includes sentiment/heat dashboard.
4. **研究報告 (Research)** `/reports` — Daily auto-fetch from IMF, BIS, Fed, ECB, BOJ, BOE, NBER. Dual-mode: RSS for working feeds, **RePEc/IDEAS HTML scraping** for institutions with broken RSS (IMF, ECB, NBER). Same preview → select → save flow.
5. **市場儀表板 (Dashboard)** `/dashboard` — Market indicators, sentiment charts, heat map.
6. **YouTube 監控** `/youtube` — Monitors YouTube channels for new videos, stores in `YoutubeVideo` table with `is_new` flag.
7. **系統設定 (Settings)** `/settings` — Sources, notifications, Google Sheets, AI model, radar topics.

### Backend Layer Structure
- **`routers/`** — FastAPI endpoints. Each router has a `/api/{prefix}` path.
- **`services/`** — Business logic. Each service wraps an external API or computation engine.
- **`scheduler/jobs.py`** — Four async jobs: `radar_scan` (5min), `market_check` (60min), `daily_news_fetch` (daily 8:00), `daily_research_fetch` (daily 10:00).
- **`database.py`** — SQLAlchemy ORM models + `_migrate_db()` for idempotent schema migrations + `_seed_defaults()` for initial data. Seeds only run when tables are empty.

### Key Design Decisions

- **AI is never auto-triggered** in scans or searches. The `analysis` field on Alert starts as `None`; user triggers via `POST /api/radar/alerts/{id}/analyze` or `POST /api/search/topic/analyze`.
- **AI Factory pattern** (`services/ai_factory.py`): `get_ai_service()` returns either `gemini_ai` or `claude_ai` module based on `DEFAULT_AI_MODEL` config. Both expose identical interfaces: `analyze_news()`, `analyze_news_for_alert()`, `search_and_analyze()`, `analyze_market_signal()`. **Gemini is default** (free tier).
- **Signal conditions** use priority-based evaluation — first matching condition wins. Market alerts fire only on **state change** (prevents duplicates).
- **Position exposure** matching (`services/exposure.py`) uses keyword scoring: symbol match (+3), name match (+2), category match (+0.5).
- **Google Sheets** integration: GAS Web App URL (`GOOGLE_APPS_SCRIPT_URL`) is preferred for writes. Service Account JSON is legacy fallback. Sheet1 = positions (read), Sheet2 = news archive (append).
- **Research feed dual-mode** (`services/research_feed.py`): Detects URL pattern — `ideas.repec.org` URLs use HTML scraping (listing page → parallel detail page fetch for metadata); all other URLs use standard RSS/feedparser. This exists because IMF, ECB, and NBER have broken RSS feeds.
- **WebSocket** broadcasts four event types: `radar_alert`, `market_alert`, `daily_summary`, `research_summary`.

### Radar Scan Flow (`scheduler/jobs.py → _radar_scan_inner`)

Three article sources are collected into `new_articles` **before** any saving or early-return:

1. **RSS sources** — `hours_back=1`, all active `MonitorSource` where `type="rss"`
2. **General Google News** — each topic in `SystemConfig["radar_topics"]`, `max_results=5`, `hours_back` from `SystemConfig["radar_hours_back"]` (default 24h)
3. **Topic keyword searches** — every active `Topic` runs `_multi_search_topic()` with its boolean keywords, results merged into `new_articles` (not just `TopicArticle`). This means user-defined boolean keyword topics **do** generate radar alerts.

After collection, articles are deduplicated against `Article` DB by URL and title. If nothing new, scan exits. Otherwise: save to `Article` DB + `TopicArticle`, then create one Alert covering all new articles.

**Dedup key** format: `scan:{YYYYMMDDHH}:{md5(first_title)[:16]}` — same lead story in the same clock-hour is silently skipped. The `Alert.dedup_key` column has a `UNIQUE` constraint as a DB-level guard against `--reload` race conditions.

**`--reload` cross-process lock**: On startup, a 240-second DB-level timestamp lock in `SystemConfig["radar_scan_lock"]` prevents two uvicorn worker processes from scanning simultaneously. First scan fires 3 minutes after startup to let old process die.

**Topic keyword caps**: `_RADAR_MAX_QUERIES=10` queries per topic, `_RADAR_CONCURRENCY=3` parallel Google News requests.

### Alert Content Encoding

`Alert.content` is a newline-separated list of article lines, each with an embedded severity prefix:
```
{critical}[Reuters] 台股崩盤 (關鍵字：台股 OR 大盤)
{high}[Bloomberg] 降息預期升溫
{low}[Yahoo Finance] 市場小幅波動
```

`Alert.source_urls` is a JSON array where each URL has the same prefix: `{high}https://...`

The frontend (`RadarPage`) parses these with `parseSourceUrl()` and `splitArticleLines()` to render per-article severity badges and enable filtering by severity level.

### Severity Assessment

Defined in `scheduler/jobs.py` (`_assess_severity_single`) and user-overridable via `SystemConfig["severity_critical_keywords"]` / `SystemConfig["severity_high_keywords"]` (edited in Settings page). Falls back to hardcoded defaults if not set. Returns `critical`, `high`, or `low` only — `medium` is not used by the scan engine (only the market signal path uses it).

The frontend (`NewsDBPage`, `RadarPage`) mirrors the same keyword lists client-side for display purposes.

### `SystemConfig` — Runtime Config Store

Besides app settings in `.env`, many runtime preferences are stored in `SystemConfig` (key/value table):

| Key | Description |
|-----|-------------|
| `radar_topics` | JSON array of general Google News search terms |
| `radar_hours_back` | Hours back for Google News search (default 24) |
| `severity_critical_keywords` | User-overridable critical keyword list (JSON) |
| `severity_high_keywords` | User-overridable high keyword list (JSON) |
| `radar_scan_lock` | ISO timestamp — cross-process dedup guard |
| `line_last_reply_at` | ISO timestamp — last time LINE news query was answered (unread baseline) |
| `line_last_yt_reply_at` | ISO timestamp — last time LINE YouTube query was answered (unread baseline) |

### LINE Webhook Command System (`routers/line_webhook.py`)

Bot only responds to specific commands — all other messages are silently ignored:

| Input pattern | Response |
|---------------|----------|
| `通知` | Unread critical news alerts since last query (updates `line_last_reply_at`) |
| `通知1天` / `通知今日` / `通知3小時` | Critical news from that time range |
| `yt` / `YT` / `yt通知` | Unread YouTube videos since last query (updates `line_last_yt_reply_at`) |
| `yt1天` / `yt今日` / `yt3小時` | YouTube videos from that time range |
| anything else | no reply |

Detection: `is_yt = user_text[:2].lower() == "yt"`, `is_news = not is_yt and "通知" in user_text`.

### Database (SQLite)

Twelve models in `backend/database.py`: `Article`, `Alert`, `MarketWatchItem`, `SignalCondition`, `MonitorSource`, `NotificationSetting`, `Topic`, `TopicArticle`, `ResearchReport`, `SystemConfig`, `YoutubeChannel`, `YoutubeVideo`. The DB file lives at `data/financial_radar.db`. To re-seed defaults, delete the DB file and restart.

`YoutubeVideo.is_new` — `True` until user marks as seen. Used by LINE webhook for unread YT queries.

`MonitorSource.type` field values: `rss`, `website`, `social`, `newsapi`, `research`, `person`. Research sources use `type="research"` and are fetched separately from news RSS sources.

`TopicArticle.add_source`: `"radar"` (added by scheduler) or `"manual"` (added by user search).

### Frontend Structure

- **Pages:** `RadarPage`, `SearchPage`, `NewsDBPage`, `ReportsPage`, `DashboardPage`, `SettingsPage`
- **API client:** `frontend/src/services/api.js` — Axios instance with 60s timeout, exports `radarAPI`, `searchAPI`, `newsAPI`, `settingsAPI`, `topicsAPI`, `reportsAPI`, plus `resolveUrl()` utility for Google News redirect resolution.
- **Real-time:** `useWebSocket` hook subscribes to backend WebSocket for live alerts.
- **Styling:** Tailwind CSS dark theme, custom classes `card`, `card-hover`, `btn-primary`, `btn-secondary`, `btn-danger`, `input` defined in `index.css`.
- **Severity display** (`NewsDBPage`): `assessSeverity(title, content)` runs client-side with the same keyword lists as the backend. `SeverityBadge` renders text pills (緊急/高/低). Not a server field — computed on render.

## Configuration

Copy `.env.example` to `.env`. Key variables:
- `GEMINI_API_KEY` — Recommended (free tier), default AI engine
- `GEMINI_MODEL` — Default `gemini-2.5-flash`
- `DEFAULT_AI_MODEL=gemini` — Switch to `claude` to use Anthropic instead
- `ANTHROPIC_API_KEY` — Required only if using Claude as AI engine
- `NEWS_API_KEY` — For NewsAPI headline fetching
- `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_CHANNEL_SECRET` — LINE Bot webhook (passive reply, free). `LINE_TARGET_ID` left empty disables active push while keeping passive reply active.
- `LINE_NOTIFY_TOKEN` — Legacy LINE Notify (deprecated, use Messaging API instead)
- `GOOGLE_APPS_SCRIPT_URL` — Preferred method for Google Sheets write (GAS Web App)
- `GOOGLE_SHEETS_CREDENTIALS_FILE` + `GOOGLE_SHEETS_SPREADSHEET_ID` — Legacy method (Service Account JSON)
- `RADAR_INTERVAL_MINUTES`, `MARKET_CHECK_INTERVAL_MINUTES` — Scheduler timing (fixed-interval, not post-completion)

## API Route Prefixes

| Prefix | Router | Purpose |
|--------|--------|---------|
| `/api/radar` | `routers/radar.py` | Alerts CRUD, market data, watchlist, signal conditions |
| `/api/search` | `routers/search.py` | Topic search, AI analysis, positions |
| `/api/news` | `routers/news_db.py` | Article CRUD, fetch preview, save-selected, sentiment |
| `/api/topics` | `routers/topics.py` | Topic CRUD, per-topic articles, Google News search+import |
| `/api/research` | `routers/research.py` | Research institutions, reports CRUD, fetch preview, save-selected |
| `/api/youtube` | `routers/youtube.py` | YouTube channel CRUD, video fetch, mark-as-seen |
| `/api/line/webhook` | `routers/line_webhook.py` | LINE Bot webhook receiver (POST only, signature-verified) |
| `/api/settings` | `routers/settings.py` | Monitor sources, notifications, Google Sheets, AI model config |
| `/api/utils/resolve-url` | `main.py` | Follow redirects, return final article URL (used by copy buttons) |
| `/api/utils/resolve-stored-urls` | `main.py` | One-time background job: resolve all Google News redirect URLs in DB |
| `/ws` | `main.py` | WebSocket for real-time broadcasts |
