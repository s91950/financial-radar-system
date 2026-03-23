# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

金融即時偵測系統 (Financial Real-time Detection System) — a three-module system for monitoring financial markets, aggregating news, and matching position exposure. Built for senior financial analysts who need real-time alerts via LINE/Email/Web with event summaries, position exposure, and source links.

**Language:** All UI text and comments are in Traditional Chinese (繁體中文). AI analysis output should also be in Traditional Chinese.

## Commands

### Backend (FastAPI + Python 3.10+)
```bash
# Install dependencies
pip install -r backend/requirements.txt

# Start dev server (from project root)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Health check
curl http://localhost:8000/api/health
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
                                  ├── WebSocket (/ws) — real-time alert broadcasting
                                  └── APScheduler — 3 background jobs
```

### Three Modules
1. **即時雷達 (Radar)** — Auto-scans RSS + NewsAPI every 5min, creates alerts with position exposure. AI analysis is **on-demand only** (user clicks button) to save API costs.
2. **主題搜尋 (Search)** — Two-step flow: search returns news + auto-matched exposure first, then user optionally triggers AI deep analysis.
3. **新聞資料庫 (News DB)** — Fetch returns a **preview** (not auto-saved). User selects which articles to save to SQLite + Google Sheets. Includes sentiment/heat dashboard.

### Backend Layer Structure
- **`routers/`** — FastAPI endpoints. Prefixed under `/api/radar`, `/api/search`, `/api/news`, `/api/settings`.
- **`services/`** — Business logic. Each service wraps an external API or computation engine.
- **`scheduler/jobs.py`** — Three async jobs: `radar_scan` (5min), `market_check` (60min), `daily_news_fetch` (daily 8:00).
- **`database.py`** — SQLAlchemy ORM models + `_seed_defaults()` for initial data (11 RSS sources, 16 market items, signal conditions, notification channels). Seeds only run when tables are empty.

### Key Design Decisions
- **AI is never auto-triggered** in radar scans or searches. The `analysis` field on Alert starts as `None`; user triggers via `POST /api/radar/alerts/{id}/analyze` or `POST /api/search/topic/analyze`.
- **Signal conditions** use priority-based evaluation — first matching condition wins. Alerts fire only on **state change** (prevents duplicate alerts).
- **Position exposure** matching (`services/exposure.py`) uses keyword scoring: symbol match (+3), name match (+2), category match (+0.5).
- **Google Sheets** is dual-purpose: Sheet1 = positions (read), Sheet2 = news archive (append).
- **WebSocket** broadcasts three event types: `radar_alert`, `market_alert`, `daily_summary`.

### Database (SQLite)
Six models in `backend/database.py`: `Article`, `Alert`, `MarketWatchItem`, `SignalCondition`, `MonitorSource`, `NotificationSetting`. The DB file lives at `data/financial_radar.db`. To re-seed defaults, delete the DB file and restart.

### Frontend Structure
- **Pages:** `RadarPage`, `SearchPage`, `NewsDBPage`, `SettingsPage` (React Router at `/`, `/search`, `/news`, `/settings`)
- **API client:** `frontend/src/services/api.js` — Axios instance with 60s timeout, exports `radarAPI`, `searchAPI`, `newsAPI`, `settingsAPI`
- **Real-time:** `useWebSocket` hook in pages subscribes to backend WebSocket for live alerts
- **Styling:** Tailwind CSS dark theme, custom classes `card`, `btn-primary`, `btn-secondary`, `input` defined in `index.css`

## Configuration

Copy `.env.example` to `.env`. Key variables:
- `ANTHROPIC_API_KEY` — Required for AI analysis features (Claude Sonnet 4)
- `NEWS_API_KEY` — Required for NewsAPI headline fetching
- `LINE_NOTIFY_TOKEN` — Optional, for LINE push notifications
- `GOOGLE_SHEETS_CREDENTIALS_FILE` + `GOOGLE_SHEETS_SPREADSHEET_ID` — Optional, for position data and news archiving (Service Account JSON key)
- `RADAR_INTERVAL_MINUTES`, `MARKET_CHECK_INTERVAL_MINUTES` — Scheduler timing

## API Route Prefixes

| Prefix | Router | Purpose |
|--------|--------|---------|
| `/api/radar` | `routers/radar.py` | Alerts CRUD, market data, watchlist, signal conditions |
| `/api/search` | `routers/search.py` | Topic search, AI analysis, positions |
| `/api/news` | `routers/news_db.py` | Article CRUD, fetch preview, save-selected, sentiment |
| `/api/settings` | `routers/settings.py` | Monitor sources, notifications, Google Sheets config |
| `/ws` | `main.py` | WebSocket for real-time broadcasts |
