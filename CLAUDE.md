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

### Modules (7 pages)

1. **即時雷達 (Radar)** `/` — Auto-scans RSS + Google News every 5min, creates alerts with position exposure. AI analysis is **on-demand only** (user clicks button) to save API costs.
2. **主題追蹤 (Topics)** `/search` — User-defined topics with boolean keywords. Radar auto-imports matching articles AND merges them into radar alerts.
3. **新聞資料庫 (News DB)** `/news` — Fetch returns a **preview** (not auto-saved). User selects which articles to save to SQLite + Google Sheets. Includes sentiment/heat dashboard.
4. **研究報告 (Research)** `/reports` — Daily auto-fetch from IMF, BIS, Fed, ECB, BOJ, BOE, NBER. Dual-mode: RSS for working feeds, **RePEc/IDEAS HTML scraping** for institutions with broken RSS (IMF, ECB, NBER). Same preview → select → save flow.
5. **市場儀表板 (Dashboard)** `/dashboard` — Market indicators, sentiment charts, heat map.
6. **YouTube 監控** `/youtube` — Monitors YouTube channels for new videos, stores in `YoutubeVideo` table with `is_new` flag.
7. **系統設定 (Settings)** `/settings` — Sources, notifications, Google Sheets, AI model, radar topics.

### Backend Layer Structure
- **`routers/`** — FastAPI endpoints. Each router has a `/api/{prefix}` path.
- **`services/`** — Business logic. Key services:
  - `ai_factory.py` — selects Gemini or Claude based on config
  - `exposure.py` — position keyword scoring
  - `finance_filter.py` — local financial relevance scoring (TF-IDF approximation, no API): `compute_finance_relevance(title, content) → float`. Three-tier vocabulary: `FINANCE_CORE` (×3 weight), `FINANCE_CONTEXT` (×1), `NON_FINANCE_INDICATORS` (−2 penalty). Formula: `(core×3 + context − non_fin×2) / sqrt(word_count)`, clipped to [0, 1].
  - `simple_ner.py` — rule-based entity extraction (stock codes, companies, central banks, currencies) used to enrich `exposure_summary` when no position match is found
  - `mops_scraper.py` — 公開資訊觀測站 material disclosure scraper. MOPS fully migrated to Vue SPA in late 2025; the old AJAX HTML endpoint (`mops/web/ajax_t05sr01`) is blocked by security policy. Uses new JSON API: `POST https://mops.twse.com.tw/mops/api/home_page/t05sr01_1` with `{"count": N, "marketKind": "sii"|"otc"}`. Dates in 民國 format (`115/04/11`). Fetches up to 100 items per market type (sii + otc).
  - `cnyes_scraper.py` — 鉅亨網 JSON API fetcher. Uses `api.cnyes.com/media/api/v1/newslist/category/{category}`.
  - `worldbank_scraper.py` — World Bank JSON API fetcher. Uses `search.worldbank.org/api/v2/news?format=json`. Fields use `{"cdata!": "..."}` wrapper. Filters English-only in code (API `lang_exact` param is unstable).
  - `fsc_scraper.py` — 金管會 (FSC) HTML scraper. FSC RSS feed is broken (returns HTML), so scrapes `news_list.jsp` page with BeautifulSoup. ~15 news links per page. Dates in 民國 format.
  - `caixin_scraper.py` — 財新 Caixin Global HTML scraper. Caixin RSS returns 403, so scrapes `/news/` page. Article URLs contain date patterns (`/YYYY-MM-DD/`). ~25 articles per page.
  - **Website scraper dispatch** (`_fetch_website_source()` in `jobs.py`): URL-based routing via `is_*_url()` predicates → `cnyes_scraper` | `worldbank_scraper` | `fsc_scraper` | `caixin_scraper` | generic `web_scraper`. To add a new scraper: create `is_xxx_url()` + `fetch_xxx()`, add routing in `_fetch_website_source()`, and add test support in `settings.py` `test_rss_source()`.
  - `research_feed.py` — dual-mode RSS/HTML scraper for research institutions
  - `rss_feed.py` — RSS parser + keyword filtering. `fetch_multiple_feeds(feeds, ...)` overrides each article's `source` field with `MonitorSource.name` (prevents verbose RSS feed titles like "經濟日報：不僅新聞速度 更有脈絡深度" or Google News query strings from appearing in UI). When `return_raw=True` returns `(filtered_articles, all_raw_articles)` tuple; raw pool used for topic cross-matching in Pass A2. Module-level `_parse_topic_groups(topic)` and `_extract_display_kw(topic, text_lower)` are imported by `jobs.py`. `_annotate_matched_terms(article, keywords)` — used in `fetch_all` mode: iterates ALL keywords, collects every term that appears (deduped), but only if the keyword's full boolean AND-condition is satisfied.
- **`scheduler/jobs.py`** — Four async jobs: `radar_scan` (5min), `market_check` (60min), `daily_news_fetch` (daily 8:00), `daily_research_fetch` (daily 10:00).
- **`database.py`** — SQLAlchemy ORM models + `_migrate_db()` for idempotent schema migrations + `_seed_defaults()` for initial data. Seeds only run when tables are empty.
- **`scripts/`** — Auxiliary tools (none are part of the main app runtime):
  - `gas_digest.gs` — Google Apps Script digest
  - `perplexity_digest.py` — Perplexity API integration
  - `notebooklm_hourly.py` — local Windows Task Scheduler job: pulls critical alerts from API, imports to NotebookLM, saves analysis to `scripts/nlm_reports/`
  - `sync_vm_settings.py` — reads local SQLite DB and pushes all settings (system_config, monitor_sources, topics) to the production VM via REST API. Run: `python scripts/sync_vm_settings.py http://<VM_IP>`. Uses URL alias map to handle sources that changed URLs between local and VM.
  - `check_sources_health.py` — async health check for all monitor sources. Dispatches to the same scraper logic as the backend (rss, cnyes, worldbank, fsc, caixin, mops). Run: `python scripts/check_sources_health.py [http://<VM_IP>] [--active-only] [-v]`. Requires `pip install httpx feedparser beautifulsoup4`.

### Key Design Decisions

- **AI is never auto-triggered** in scans or searches. The `analysis` field on Alert starts as `None`; user triggers via `POST /api/radar/alerts/{id}/analyze` or `POST /api/search/topic/analyze`.
- **AI Factory pattern** (`services/ai_factory.py`): `get_ai_service()` returns either `gemini_ai` or `claude_ai` module based on `DEFAULT_AI_MODEL` config. Both expose identical interfaces: `analyze_news()`, `analyze_news_for_alert()`, `search_and_analyze()`, `analyze_market_signal()`. **Gemini is default** (free tier).
- **Signal conditions** use priority-based evaluation — first matching condition wins. Market alerts fire only on **state change** (prevents duplicates).
- **Position exposure** matching (`services/exposure.py`) uses keyword scoring: symbol match (+3), name match (+2), category match (+0.5).
- **Google Sheets** integration: GAS Web App URL (`GOOGLE_APPS_SCRIPT_URL`) is preferred for writes. Service Account JSON is legacy fallback. Sheet1 = positions (read), Sheet2 = news archive (append).
- **Research feed dual-mode** (`services/research_feed.py`): Detects URL pattern — `ideas.repec.org` URLs use HTML scraping (listing page → parallel detail page fetch for metadata); all other URLs use standard RSS/feedparser. This exists because IMF, ECB, and NBER have broken RSS feeds.
- **WebSocket** broadcasts four event types: `radar_alert`, `market_alert`, `daily_summary`, `research_summary`.

### Radar Scan Flow (`scheduler/jobs.py → _radar_scan_inner`)

Four article sources are collected into `new_articles` **before** any saving or early-return:

1. **RSS sources** — all active `MonitorSource` where `type in ("rss", "social")`, filtered by source keywords OR global `radar_topics` (union, not exclusive). `fetch_multiple_feeds(return_raw=True)` also returns the unfiltered raw pool for Pass A2.
2. **MOPS** — active `MonitorSource` where `type="mops"`, fetches 公開資訊觀測站 material disclosures via `services/mops_scraper.py`
3. **General Google News** — each topic in `SystemConfig["radar_topics"]` (TW) + `SystemConfig["radar_topics_us"]` (US), `max_results=20`, `hours_back` from `SystemConfig["radar_hours_back"]` (default 24h). Skipped if `_skip_gn=True`. If `gn_critical_only=true`, each GN article is pre-assessed — non-critical articles are discarded before being added to `new_articles` (RSS articles are never filtered this way).
4. **Topic keyword searches** — every active `Topic` processes articles in two sub-passes:
   - **Pass A2** (new, RSS-only mode only): when `_skip_gn=True`, the raw unfiltered RSS pool is cross-matched against the topic's boolean keywords. Catches articles that passed RSS fetch but didn't match the radar topic filter.
   - **Pass B** (skipped when `_skip_gn=True`): dedicated Google News search for this topic using `_multi_search_topic()`. If `gn_critical_only=true`, non-critical GN results are dropped (but still saved to `TopicArticle`).

   Results from both passes are merged into `new_articles`, so topic-tracked articles **do** generate radar alerts.

**RSS priority mode**: if `radar_rss_min_articles > 0` and RSS has collected ≥ that many articles (and not a forced scan), Google News steps are skipped entirely. Controlled by `SystemConfig["radar_rss_min_articles"]` (default `"0"`, disabled). `radar_rss_only=true` also skips Google News unconditionally. Both cases set `_skip_gn = True`.

**`fetch_all` source mode**: `MonitorSource.fetch_all=True` bypasses keyword filtering entirely — all articles from that source enter `new_articles`. Keyword matching still runs via `_annotate_matched_terms` to produce badge labels, but only for keywords whose full boolean AND-condition is satisfied (no partial-match badges). Articles from `fetch_all` sources carry `fetch_all_source=True` in the article dict, which causes the finance filter to skip them (they pass unconditionally regardless of relevance score). Finance relevance is still computed for composite scoring.

**Finance filter** (optional, off by default): if `finance_filter_enabled=true`, articles scoring below `finance_relevance_threshold` (default 0.15) are dropped before saving. Articles with `fetch_all_source=True` are exempt. Even when disabled, `finance_relevance` is still computed per article for the composite score.

**Article scoring** (`_compute_article_scores()`): runs before `db.add(Article(...))` and writes five fields: `decay_factor = exp(-0.1 × hours_elapsed)`, `novelty_score = 1/(1 + similar_count)` (Jaccard ≥ 0.5 against `seen_content_fps`), `finance_relevance` (from filter above), `intensity_score = abs((pos−neg)/total)` using sentiment keywords, `composite_score = decay × novelty × max(relevance, 0.05) × (0.5 + 0.5 × intensity)`.

After collection, articles pass through **three dedup layers** before saving:
1. In-memory exact URL + title match
2. DB check against `Article` table (URL + title)
3. **Content fingerprint** (`_article_fingerprint` → Jaccard similarity ≥ 0.65) — catches same story from different sources with different titles. `seen_content_fps` list is shared across all 4 steps.

If nothing new, scan exits. Otherwise: save to `Article` DB + `TopicArticle`, then create one Alert.

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

`_assess_severity_single()` in `scheduler/jobs.py` uses a **multi-dimensional scoring model**:

1. **Boolean rules** (highest priority) — user-configured `SystemConfig["severity_rules"]` e.g. `"暴跌 AND 台股" → critical`. First match wins.
2. **Multi-dimensional score** (keyword hits only if no rule matches):
   - `base_score`: critical=3.0, high=2.0 (after negation filtering)
   - **Negation filter** (`_has_negation_before`): keywords preceded by 不/沒/未/不會 etc. within 6 chars are excluded — "不會崩盤" does not trigger critical
   - **Source credibility** (`_get_source_weight`): Reuters/Bloomberg ×1.5, official sources (Fed/金管會) ×1.6, general ×1.0. **Unknown GN source penalty**: if `source_w == 1.0` AND the article came from Google News (`origin == "gn"`) AND the source name is not in `_known_source_names` (frozenset built from active `MonitorSource` names at scan start) → `source_w = 0.65`, making high/critical harder to trigger for low-authority outlets.
   - **Confirmation factor**: keyword in both title AND body → ×1.3
   - **Multi-keyword bonus**: each additional matched keyword → +0.1, max ×1.3
   - Threshold: ≥3.5→critical, ≥2.0→high, else→low
3. **Time decay** (`_apply_time_decay`): articles older than `SystemConfig["severity_decay_hours"]` (default 6h) are downgraded one level (critical→high, high→low).

Returns `critical`, `high`, or `low` only — `medium` is not used by the scan engine.

The frontend (`NewsDBPage`, `RadarPage`) mirrors keyword lists client-side for display purposes.

### `SystemConfig` — Runtime Config Store

Besides app settings in `.env`, many runtime preferences are stored in `SystemConfig` (key/value table):

| Key | Description |
|-----|-------------|
| `radar_topics` | JSON array of general Google News search terms (TW/Chinese) |
| `radar_topics_us` | JSON array of US/English Google News search terms |
| `radar_hours_back` | Hours back for Google News search (default 24) |
| `radar_interval_minutes` | Radar scan interval in minutes (overrides `.env`, reloaded at startup) |
| `radar_rss_only` | `"true"` to skip Google News and only use RSS sources |
| `severity_critical_keywords` | User-overridable critical keyword list (JSON) |
| `severity_high_keywords` | User-overridable high keyword list (JSON) |
| `severity_rules` | Boolean severity rules (JSON array of `{condition, severity}`) |
| `severity_decay_hours` | Hours after which severity is downgraded one level (default 6) |
| `radar_scan_lock` | ISO timestamp — cross-process dedup guard |
| `line_last_reply_at` | ISO timestamp — last time LINE news query was answered (unread baseline) |
| `line_last_yt_reply_at` | ISO timestamp — last time LINE YouTube query was answered (unread baseline) |
| `radar_rss_min_articles` | If RSS collects ≥ N articles, skip Google News (default `"0"` = disabled) |
| `finance_filter_enabled` | `"true"` to drop articles below relevance threshold (default `"false"`) |
| `finance_relevance_threshold` | Min finance relevance score to keep article (default `"0.15"`) |
| `gn_critical_only` | `"true"` to pre-filter Google News results to critical severity only; RSS articles unaffected (default `"false"`) |

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

`MonitorSource.type` field values: `rss`, `website`, `social`, `newsapi`, `research`, `person`, `mops`. Research sources use `type="research"` and are fetched separately from news RSS sources. `mops` sources are fetched via `services/mops_scraper.py`. `website` sources are routed by `_fetch_website_source()` to specialized scrapers (cnyes, worldbank, fsc, caixin) or a generic web_scraper fallback.

**Scraping limitations**: IMF (`imf.org`) is fully blocked by Akamai Bot Manager (all endpoints return 403) — uses Google News `site:imf.org when:7d` RSS as proxy. 商周 (`businessweekly.com.tw`) also blocks most pages — uses Google News proxy. UDN financial RSS moved from `udn.com/rssfeed` (broken, returns empty entries) to `money.udn.com/rssfeed`.

`MonitorSource.fetch_all` — boolean (default `False`). When `True`, skips keyword filtering so all articles from the source enter the radar; keyword badges are still annotated but only when the full boolean condition matches. Applies to **all source types** including `mops`. Added via `_migrate_db()` `ALTER TABLE`.

`MonitorSource.sort_order` — integer (default `0`). User-controlled display order in SettingsPage; lower = earlier. Initialized from `id` order on first migration. Updated via `PUT /api/settings/sources/reorder` (list of IDs in desired order).

`TopicArticle.add_source`: `"radar"` (added by scheduler) or `"manual"` (added by user search).

`Article` has six extra columns added via `_migrate_db()`: `composite_score`, `finance_relevance`, `novelty_score`, `decay_factor`, `intensity_score` (all `REAL`, nullable, computed by `_compute_article_scores()` in `jobs.py` at save time) + `matched_keyword VARCHAR` (nullable, set from preview data when user saves selected articles via `POST /api/news/save-selected`).

### Frontend Structure

- **Pages:** `RadarPage`, `SearchPage`, `NewsDBPage`, `ReportsPage`, `DashboardPage`, `SettingsPage`
- **API client:** `frontend/src/services/api.js` — Axios instance with 60s timeout, exports `radarAPI`, `searchAPI`, `newsAPI`, `settingsAPI`, `topicsAPI`, `reportsAPI`, plus `resolveUrl()` utility for Google News redirect resolution.
- **Real-time:** `useWebSocket` hook subscribes to backend WebSocket for live alerts.
- **Styling:** Tailwind CSS dark theme, custom classes `card`, `card-hover`, `btn-primary`, `btn-secondary`, `btn-danger`, `input` defined in `index.css`.
- **Severity display** (`NewsDBPage`): `assessSeverity(title, content)` runs client-side with the same keyword lists as the backend. `SeverityBadge` renders text pills (緊急/高/低). Not a server field — computed on render.
- **SettingsPage source list**: drag handle (`⠿`) for drag-to-sort (calls `PUT /sources/reorder`); hover name to reveal inline rename input (Enter/blur saves, Escape cancels). All source types including MOPS have a `fetch_all` toggle. Keyword category manager uses `CAT_COLORS` (8 colours) — clicking a keyword pill opens a popover to assign it to a named category.
- **Routing constraint**: `PUT /api/settings/sources/reorder` must be declared **before** `PUT /api/settings/sources/{source_id}` in `settings.py` or FastAPI will match `"reorder"` as a source ID.

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
| `/api/news` | `routers/news_db.py` | Article CRUD, fetch preview, save-selected, sentiment. `POST /fetch` supports `source_type`: `"sources_only"` (RSS + website sources, default) or `"gn_only"` (Google News). When no query, uses radar_topics + active Topic keywords. Query strings are split via `_split_query_terms()` (spaces + ASCII/CJK boundary) for OR matching. Boolean topics dispatched via `_gn_fetch_topic()` → `_multi_search_topic`. |
| `/api/topics` | `routers/topics.py` | Topic CRUD, per-topic articles, Google News search+import |
| `/api/research` | `routers/research.py` | Research institutions, reports CRUD, fetch preview, save-selected |
| `/api/youtube` | `routers/youtube.py` | YouTube channel CRUD, video fetch, mark-as-seen |
| `/api/line/webhook` | `routers/line_webhook.py` | LINE Bot webhook receiver (POST only, signature-verified) |
| `/api/settings` | `routers/settings.py` | Monitor sources (including `fetch_all`, `sort_order` fields), notifications, Google Sheets, AI model config, finance filter toggle+threshold, RSS priority threshold, GN critical-only toggle. `PUT /sources/reorder` — bulk sort_order update (list of IDs, must be registered **before** `PUT /sources/{id}` to avoid FastAPI routing conflict). `POST /sources/{id}/test-rss` supports all types: `mops`, `website` (dispatches to cnyes/worldbank/fsc/caixin scrapers via same `is_*_url()` routing), and `rss`/`social`. |
| `/api/utils/resolve-url` | `main.py` | Follow redirects, return final article URL (used by copy buttons) |
| `/api/utils/resolve-stored-urls` | `main.py` | One-time background job: resolve all Google News redirect URLs in DB |
| `/ws` | `main.py` | WebSocket for real-time broadcasts |

## NotebookLM Local Automation (`scripts/notebooklm_hourly.py`)

Runs on the **local Windows machine** via Task Scheduler (not on the VM). Requires `pip install notebooklm-py requests` and `notebooklm login` (browser-based auth, saves to `~/.notebooklm/storage_state.json`; re-run when auth expires).

**Flow**: fetch alerts from VM API → filter by time window + severity → build Markdown → `await client.sources.add_text(NOTEBOOK_ID, ...)` → `await client.chat.ask(NOTEBOOK_ID, question)` → save result to `scripts/nlm_reports/YYYYMMDD_HHMM.txt`.

Config in `scripts/.env.local` (copy from `scripts/.env.local.example`): `API_BASE_URL`, `NOTEBOOK_ID`, `HOURS_BACK`, `MIN_SEVERITY`, `RESULT_PUSH_LINE`.

**notebooklm-py 0.3.4 API**: `async with await NotebookLMClient.from_storage() as client:` — note the double `await`. Sub-clients: `client.sources` (`add_text`, `add_url`, `add_file`), `client.chat` (`ask` → returns `AskResult` with `.answer`), `client.notebooks` (`list`, `create`, `get`).
