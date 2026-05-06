# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 修改後 VM 同步提示規則

每次完成程式碼修改後，必須執行以下其中一項：

1. **需要更新 VM** — 在回應最後加一行：
   > 「此修改需要更新到 VM，是否現在執行 `git push` 並在 VM 上 `git pull && sudo systemctl restart financial-radar`？」

2. **不需要更新 VM** — 在回應最後加一行說明原因，例如：
   > 「此修改僅影響本地腳本（`scripts/`），不需更新 VM。」

**判斷基準：**
- 需要更新 VM：`backend/`、`frontend/`、`deploy/` 下的任何檔案修改
- 不需要更新 VM：`scripts/` 下的本地腳本、`CLAUDE.md`、`README.md`、純本地設定檔

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
- **SSH key**: `C:\Users\User\.ssh\google_compute_engine` — use with `ssh -i` to connect to VM

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

### Modules (9 pages)

1. **即時雷達 (Radar)** `/` — Auto-scans RSS + Google News every 5min, creates alerts with position exposure. AI analysis is **on-demand only** (user clicks button) to save API costs.
2. **主題追蹤 (Topics)** `/search` — User-defined topics with boolean keywords. Radar auto-imports matching articles AND merges them into radar alerts.
3. **新聞資料庫 (News DB)** `/news` — Fetch returns a **preview** (not auto-saved). User selects which articles to save to SQLite + Google Sheets. Includes sentiment/heat dashboard. Source and keyword filter dropdowns; source list cross-references `MonitorSource` names, ungrouped sources show as "其他". Articles display `matched_keyword` tags inline.
4. **研究報告 (Research)** `/reports` — Daily auto-fetch from IMF, BIS, Fed, ECB, BOJ, BOE, NBER. Dual-mode: RSS for working feeds, **RePEc/IDEAS HTML scraping** for institutions with broken RSS (IMF, ECB, NBER). Same preview → select → save flow.
5. **市場儀表板 (Dashboard)** `/dashboard` — Market indicators, sentiment charts, heat map.
6. **YouTube 監控** `/youtube` — Monitors YouTube channels for new videos, stores in `YoutubeVideo` table with `is_new` flag.
7. **分析結果** `/analysis` — Displays AI analysis reports. Four tabs: NLM 新聞 / NLM YouTube / Gemini 新聞 / Gemini YouTube + 手動觸發 Gemini 分析按鈕. History row for browsing past reports by date. NLM reports from local `notebooklm_hourly.py`; Gemini reports from VM-side `gemini_analysis.py` (every 3h auto). Lazy-loads from `GET /api/radar/notebooklm-report`, `GET /api/radar/notebooklm-yt-report`, `GET /api/radar/gemini-report`, `GET /api/radar/gemini-yt-report`.
8. **意見回饋 (Feedback)** `/feedback` — User submits improvement suggestions with category (功能建議/問題回報/介面改善/其他意見). History list with delete. Backend: `Feedback` model in `database.py`, `routers/feedback.py` (`GET /api/feedback/`, `POST /api/feedback/`, `DELETE /api/feedback/{id}`).
9. **系統設定 (Settings)** `/settings` — Sources, notifications, Google Sheets, AI model, radar topics.

### Backend Layer Structure
- **`routers/`** — FastAPI endpoints. Each router has a `/api/{prefix}` path.
- **`services/`** — Business logic. Key services:
  - `ai_factory.py` — selects Gemini or Claude based on config
  - `exposure.py` — position keyword scoring
  - `finance_filter.py` — local financial relevance scoring (TF-IDF approximation, no API): `compute_finance_relevance(title, content) → float`. Three-tier vocabulary: `FINANCE_CORE` (×3 weight), `FINANCE_CONTEXT` (×1), `NON_FINANCE_INDICATORS` (−2 penalty). Formula: `(core×3 + context − non_fin×2) / sqrt(word_count)`, clipped to [0, 1].
  - `simple_ner.py` — rule-based entity extraction (stock codes, companies, central banks, currencies) used to enrich `exposure_summary` when no position match is found
  - `mops_scraper.py` — 公開資訊觀測站 material disclosure scraper. MOPS fully migrated to Vue SPA in late 2025; the old AJAX HTML endpoint (`mops/web/ajax_t05sr01`) is blocked by security policy. Uses new JSON API: `POST https://mops.twse.com.tw/mops/api/home_page/t05sr01_1` with `{"count": N, "marketKind": "sii"|"otc"}`. Dates in 民國 format (`115/04/11`). Fetches up to 100 items per market type (sii + otc). **URL includes date+time** (`?TYPEK=sii&co_id=2330&d=1150411&t=1050`) so multiple disclosures from the same company each get a unique URL (prevents dedup collision in `seen_urls`).
  - `cnyes_scraper.py` — 鉅亨網 JSON API fetcher. Uses `api.cnyes.com/media/api/v1/newslist/category/{category}`.
  - `worldbank_scraper.py` — World Bank JSON API fetcher. Uses `search.worldbank.org/api/v2/news?format=json`. Fields use `{"cdata!": "..."}` wrapper. Filters English-only in code (API `lang_exact` param is unstable).
  - `fsc_scraper.py` — 金管會 (FSC) HTML scraper. FSC RSS feed is broken (returns HTML), so scrapes `news_list.jsp` page with BeautifulSoup. ~15 news links per page. Dates in 民國 format.
  - `caixin_scraper.py` — 財新 Caixin Global HTML scraper. Caixin RSS returns 403, so scrapes `/news/` page. Article URLs contain date patterns (`/YYYY-MM-DD/`). ~25 articles per page.
  - `storm_scraper.py` — 風傳媒 sitemap scraper. **Currently unused**: storm.mg's CloudFront/WAF blocks GCP IP ranges (all paths return 403 from VM, even though local IPs get 200). Falls back to Google News `site:storm.mg when:3d` proxy. Code retained in case CDN policy changes.
  - `taisounds_scraper.py` — 太報 HTML scraper. No RSS; uses standard sitemap (`taisounds.com/sitemap.xml` with `lastmod`), then parallel-fetches `og:title` / `og:description` from each article page.
  - `linetoday_scraper.py` — LINE Today 國際 scraper. Next.js SSR page embeds article data in `__NEXT_DATA__` JSON — walks the object recursively to find dicts with `title + id + publishTimeUnix`. Article URL: `https://today.line.me/tw/v3/article/{id}`.
  - `udn_scraper.py` — 聯合新聞網分類頁 scraper. `udn.com/news/cate/` pages are server-side rendered HTML; BeautifulSoup finds `<a href="/news/story/...">` links with sibling `<time>` tags (YYYY-MM-DD HH:MM Taiwan time → UTC).
  - `fed_scraper.py` — 聯準會全站最新消息 scraper. Scrapes `federalreserve.gov/recentpostings.htm` (server-side rendered, no pagination), covering all content types: press releases, speeches, Beige Book, FEDS Notes, statistical releases, meeting notices. Parses `.eventlist__time time` (M/D/YYYY) + `.eventlist__event p` (type link + description). Returns `category="official"`, `source="聯準會 (Fed)"`. `is_fed_url()` matches `federalreserve.gov/recentpostings`.
  - `ctee_scraper.py` — 工商時報 RSS scraper. Fetches `ctee.com.tw/rss_web/livenews/{category}` (官方 livenews RSS, ~15 articles per refresh, 分鐘級新鮮度). Built as a custom scraper instead of generic RSS path because `<pubDate>` lacks timezone marker (e.g. `2026-05-06T11:57:13`) but is actually Taiwan local time — must convert TW+8 → UTC. `is_ctee_url()` matches `ctee.com.tw/rss_web` or `ctee.com.tw/livenews`; if a livenews page URL is given, auto-rewrites to the matching `rss_web` endpoint. Categories: `ctee` (綜合，預設), `policy`, `stock`, `finance`, `p-tax`, `industry`, `house`, `world`, `china`, `tech`, `life`. Replaces previous Google News `site:ctee.com.tw` proxy (1-3h lag).
  - `nownews_scraper.py` — NOWnews 今日新聞 Google News Sitemap scraper. Fetches `nownews.com/newsSitemap-daily.xml` — the sitemap embeds `<news:title>` and `<news:publication_date>` per `<url>` so no per-article fetch is needed. Returns ~50-60 articles within 2h on a busy day, freshness within 5-15 minutes. Replaces GN `site:nownews.com` proxy. `is_nownews_url()` matches `nownews.com` + `sitemap` substring. NowNews has no public RSS; the sitemap path is listed in `robots.txt`.
  - **Website scraper dispatch** (`_fetch_website_source()` in `jobs.py`): URL-based routing via `is_*_url()` predicates → `fed_scraper` | `cnyes_scraper` | `worldbank_scraper` | `fsc_scraper` | `caixin_scraper` | `storm_scraper` | `taisounds_scraper` | `linetoday_scraper` | `udn_scraper` | `ctee_scraper` | `nownews_scraper` | generic `web_scraper`. To add a new scraper: create `is_xxx_url()` + `fetch_xxx()`, add routing in `_fetch_website_source()`, and add test support in `settings.py` `test_rss_source()`.
  - `research_feed.py` — dual-mode RSS/HTML scraper for research institutions
  - `article_fetcher.py` — **full-body enrichment** for radar candidates. After dedup, runs `enrich_articles_with_full_body(articles, concurrency=5, timeout=5.0)` on the 5-30 surviving articles: parallel HTTP GET each `source_url`, extract `<article>`/`<main>` text and overwrite `article['content']`; also salvages `published_at` from JSON-LD `"datePublished"` / `<meta property="article:published_time">` / `<meta itemprop="datePublished">` / `<time datetime>` (in that order) when RSS didn't supply one (e.g. Nikkei Asia RSS 1.0 has no pubDate). Skips when content ≥ 500 chars AND `published_at` already set, or when URL is still `news.google.com` (unresolved). Failure is silent — falls back to RSS summary. **This is what makes exclusion-keyword filtering and severity assessment see real article body**, since RSS `summary` is usually only the title + first one or two sentences.
  - `google_news.py` — Google News RSS search + URL decode. Two-tier decode for GN article IDs: (1) base64 protobuf direct extraction for old format (no network), (2) **individual** `batchexecute` per article for new `AU_yq...` format — each article decoded independently to avoid batch response ordering issues that cause title/URL mismatch. `_DECODE_CONCURRENCY=5` limits parallel requests.
  - `rss_feed.py` — RSS parser + keyword filtering. `fetch_multiple_feeds(feeds, ...)` overrides each article's `source` field with `MonitorSource.name` as-is (no cleaning/stripping — user-defined names like "經濟日報 - 國際" are preserved verbatim). When `return_raw=True` returns `(filtered_articles, all_raw_articles)` tuple; raw pool used for topic cross-matching in Pass A2. Module-level `_parse_topic_groups(topic)` and `_extract_display_kw(topic, text_lower)` are imported by `jobs.py`. `_annotate_matched_terms(article, keywords)` — used in `fetch_all` mode: iterates ALL keywords, collects every term that appears (deduped), but only if the keyword's full boolean AND-condition is satisfied. `_resolve_gn_article_urls(articles)` — called after standard redirect resolution in `fetch_rss_feed()`; extracts article IDs from `news.google.com/rss/articles/CBMi...` URLs and decodes them via `google_news._resolve_google_news_urls()` (same two-tier decode). **Keyword matching helpers**: `_term_in_text(term, text_lower)` — uses word-boundary regex for pure-ASCII terms so "Coup" does not match "Couple"; CJK terms use substring match. `_strip_not_terms(topic)` — extracts `NOT term` / `NOT "multi word"` clauses from a keyword string before group parsing; returns `(cleaned_topic, [not_terms])`. Used by `_matches_topic()` (fail-fast if any NOT term appears in text), `_extract_display_kw()`, and `_annotate_matched_terms()`.
- **`scheduler/jobs.py`** — Seven async jobs: `radar_scan` (5min), `market_check` (60min), `daily_news_fetch` (daily, hour from `NEWS_SCHEDULE_HOUR` in server timezone — VM is UTC), `daily_research_fetch` (daily 10:00), `youtube_check` (30min), `mark_all_youtube_seen` (daily 23:00 UTC = 07:00 Taipei — bulk-clears `YoutubeVideo.is_new=False`), `gemini_analysis` (every 3h, first run 5min after startup).
- **`database.py`** — SQLAlchemy ORM models + `_migrate_db()` for idempotent schema migrations + `_seed_defaults()` for initial data. Seeds only run when tables are empty.
- **`scripts/`** — Auxiliary tools (none are part of the main app runtime):
  - `gas_digest.gs` — Google Apps Script digest
  - `perplexity_digest.py` — Perplexity API integration
  - `notebooklm_hourly.py` — local Windows Task Scheduler job (every 3 hours): pulls news articles and YouTube videos from API, imports to NotebookLM notebooks, saves analysis to `scripts/nlm_reports/`
  - `skills/` — permanent NLM source files (`PROJECT_INSTRUCTIONS_v2.md`, `SKILL_*.md`). Loaded into each notebook once via `_ensure_skill_sources()` and never deleted. Identified by `[SKILL] ` title prefix.
  - `sync_vm_settings.py` — reads local SQLite DB and pushes all settings (system_config, monitor_sources, topics) to the production VM via REST API. Run: `python scripts/sync_vm_settings.py http://<VM_IP>`. Uses URL alias map to handle sources that changed URLs between local and VM.
  - `check_sources_health.py` — async health check for all monitor sources. Dispatches to the same scraper logic as the backend (rss, cnyes, worldbank, fsc, caixin, mops). Run: `python scripts/check_sources_health.py [http://<VM_IP>] [--active-only] [-v]`. Requires `pip install httpx feedparser beautifulsoup4`.
  - `backfill_published_at.py` — one-shot tool to re-enrich existing DB rows where `Article.published_at IS NULL`. Run on VM: `cd /opt/financial-radar && ./venv/bin/python scripts/backfill_published_at.py`. Reuses `services.article_fetcher.enrich_articles_with_full_body`, so success rate depends on whether each source's HTML carries JSON-LD / OG meta dates (works well for Nikkei, less so for FSC and 聯合新聞網 which use non-standard date markup).

### Key Design Decisions

- **AI is never auto-triggered** in scans or searches. The `analysis` field on Alert starts as `None`; user triggers via `POST /api/radar/alerts/{id}/analyze` or `POST /api/search/topic/analyze`.
- **AI Factory pattern** (`services/ai_factory.py`): `get_ai_service()` returns either `gemini_ai` or `claude_ai` module based on `DEFAULT_AI_MODEL` config. Both expose identical interfaces: `analyze_news()`, `analyze_news_for_alert()`, `search_and_analyze()`, `analyze_market_signal()`. **Gemini is default** (free tier).
- **Signal conditions** use priority-based evaluation — first matching condition wins. Market alerts fire only on **state change** (prevents duplicates).
- **Position exposure** matching (`services/exposure.py`) uses keyword scoring: symbol match (+3), name match (+2), category match (+0.5).
- **Google Sheets** integration: Dual mechanism — **VM pushes instantly** via `append_news_via_gas()` (radar scan + daily fetch + user save-selected), **GAS `pullFromVM()` pulls every 30min** as backup. `GOOGLE_APPS_SCRIPT_URL` must be set on VM `.env` only; local `.env` should leave it **empty** to prevent local dev from pushing to Sheets. Service Account JSON is legacy fallback. Sheet1 = positions (read), Sheet2 = news archive (append). GAS payload fields: `入庫時間`, `標題`, `嚴重度`, `來源`, `關鍵字`, `網址`.
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

**`fetch_all` source mode**: `MonitorSource.fetch_all=True` bypasses keyword filtering entirely — all articles from that source enter `new_articles`. Keyword matching still runs via `_annotate_matched_terms` using the **union of source keywords + all radar topic keywords** to produce badge labels, but only for keywords whose full boolean AND-condition is satisfied (no partial-match badges). This ensures even sources with no configured keywords still show radar-topic badges when matched. Articles from `fetch_all` sources carry `fetch_all_source=True` in the article dict, which causes the finance filter to skip them (they pass unconditionally regardless of relevance score). Finance relevance is still computed for composite scoring.

**Finance filter** (optional, off by default): if `finance_filter_enabled=true`, articles scoring below `finance_relevance_threshold` (default 0.15) are dropped before saving. Articles with `fetch_all_source=True` are exempt. Even when disabled, `finance_relevance` is still computed per article for the composite score.

**Article scoring** (`_compute_article_scores()`): runs before `db.add(Article(...))` and writes five fields: `decay_factor = exp(-0.1 × hours_elapsed)`, `novelty_score = 1/(1 + similar_count)` (Jaccard ≥ 0.5 against `seen_content_fps`), `finance_relevance` (from filter above), `intensity_score = abs((pos−neg)/total)` using sentiment keywords, `composite_score = decay × novelty × max(relevance, 0.05) × (0.5 + 0.5 × intensity)`.

**Global exclusion keywords**: `SystemConfig["radar_exclusion_keywords"]` (JSON array) — applied after all 4 collection steps but before dedup/saving. Any article whose title+content contains an exclusion term (via `_term_in_text`) is dropped. Managed in SettingsPage "全域排除關鍵字" section.

After collection, articles pass through **three dedup layers** before saving:
1. In-memory exact URL + title match
2. DB check against `Article` table (URL + title)
3. **Content fingerprint** (`_article_fingerprint` → Jaccard similarity ≥ 0.65) — catches same story from different sources with different titles. `seen_content_fps` list is shared across all 4 steps.

**Full-body enrichment** (between dedup and exclusion filter, [jobs.py:687](backend/scheduler/jobs.py#L687)): `await enrich_articles_with_full_body(new_articles)` from `services/article_fetcher.py`. Replaces RSS-summary `content` with extracted main text, salvages `published_at` from HTML metadata. Adds 1-5s/scan but makes `radar_exclusion_keywords`, severity assessment, and DB-stored `Article.content` see real body text rather than just title + first sentence.

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

**Source-level floor + credibility**: `MonitorSource.fixed_severity` (VARCHAR, nullable) — acts as a **minimum severity floor** and **source credibility signal**:
- `critical` → always returns critical immediately (no dynamic assessment)
- `high` → floor is high + injects `source_weight_override=1.6` into dynamic assessment, making high keywords able to reach critical (e.g. 2 high keywords: `2.0×1.6×1.1=3.52≥3.5→critical`)
- `low` → floor only, no credibility boost
At scan start, a `_source_fixed_sev: dict[str, str]` map is built from active sources with this field set. The helper `_article_severity(a)` handles the three cases, then applies `max(dynamic, floor)` via `_SEVERITY_ORDER`. This applies everywhere severity is assessed: `_fmt_article_line`, `source_urls` construction, GN critical-only pre-filter, and GAS urgent-rows filter. The source list in SettingsPage shows a coloured badge (最低緊急 / 最低高風險 / 最低低風險) and a dropdown in the expanded view.

`_assess_severity_single()` in `scheduler/jobs.py` uses a **multi-dimensional scoring model**:

1. **Boolean rules** (highest priority) — user-configured `SystemConfig["severity_rules"]` e.g. `"暴跌 AND 台股" → critical`. First match wins.
2. **Multi-dimensional score** (keyword hits only if no rule matches):
   - `base_score`: critical=3.0, high=2.0 (after negation filtering)
   - **Negation filter** (`_has_negation_before`): keywords preceded by 不/沒/未/不會 etc. within 6 chars are excluded — "不會崩盤" does not trigger critical
   - **Source credibility** (`_get_source_weight`): Reuters/Bloomberg ×1.5, official sources (Fed/金管會) ×1.6, general ×1.0. **User-set high floor** → `source_weight_override=1.6` (same as official). **Unknown GN source penalty**: if `source_w == 1.0` AND the article came from Google News (`origin == "gn"`) AND the source name is not in `_known_source_names` (frozenset built from active `MonitorSource` names at scan start) → `source_w = 0.65`, making high/critical harder to trigger for low-authority outlets.
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
| `radar_exclusion_keywords` | JSON array of terms — any article containing one is dropped from all sources after collection |
| `radar_topic_categories` | JSON array of `{name, lang, keywords}` — named keyword categories for SettingsPage UI; flattened to `radar_topics`/`radar_topics_us` on save |
| `nlm_latest_report` | Full Markdown text of the latest NotebookLM news analysis report (written by `notebooklm_hourly.py` via `POST /api/radar/notebooklm-report`) |
| `nlm_report_generated_at` | ISO timestamp of when the NLM news report was generated |
| `nlm_report_source_title` | Source title string used when the news report was created in NotebookLM |
| `nlm_yt_latest_report` | Full Markdown text of the latest NotebookLM YouTube analysis report |
| `nlm_yt_report_generated_at` | ISO timestamp of when the YT report was generated |
| `nlm_yt_report_source_title` | Source title string used when the YT report was created |

### LINE Webhook Command System (`routers/line_webhook.py`)

Bot only responds to specific commands — all other messages are silently ignored:

| Input pattern | Response |
|---------------|----------|
| `分析` / any text containing `分析` | Latest NotebookLM **news** analysis report from `SystemConfig["nlm_latest_report"]` |
| `通知` | Unread critical news alerts since last query (updates `line_last_reply_at`) |
| `通知1天` / `通知今日` / `通知3小時` | Critical news from that time range |
| `yt` / `YT` / `yt通知` | Unread YouTube videos since last query (updates `line_last_yt_reply_at`) |
| `yt分析` | Latest NotebookLM **YouTube** analysis report from `SystemConfig["nlm_yt_latest_report"]` |
| `yt1天` / `yt今日` / `yt3小時` | YouTube videos from that time range |
| anything else | no reply |

Detection priority: `is_yt = user_text[:2].lower() == "yt"` → `is_analysis = not is_yt and "分析" in user_text` → `is_news = not is_yt and not is_analysis and "通知" in user_text`. Inside the `is_yt` branch, `yt分析` (i.e. `"分析" in remainder`) takes priority over the video list. The `分析` command takes priority over `通知` so "分析通知" triggers news analysis, not news. Markdown from the NLM report is stripped by `_md_to_plain()` before sending. Report is split into ≤5 LINE messages of ≤4800 chars each. Article titles in news notifications are capped at 80 characters (truncated to 78 + `…`) in `_parse_articles()` — prevents social media posts (e.g. Trump tweets from Nitter) from flooding the notification with full post text.

### Database (SQLite)

Fourteen models in `backend/database.py`: `Article`, `Alert`, `MarketWatchItem`, `SignalCondition`, `MonitorSource`, `NotificationSetting`, `Topic`, `TopicArticle`, `ResearchReport`, `SystemConfig`, `YoutubeChannel`, `YoutubeVideo`, `Feedback`, `NlmReport`. The DB file lives at `data/financial_radar.db`. To re-seed defaults, delete the DB file and restart.

`YoutubeVideo.is_new` — `True` until user marks as seen. Used by LINE webhook for unread YT queries.

`MonitorSource.type` field values: `rss`, `website`, `social`, `newsapi`, `research`, `person`, `mops`. Research sources use `type="research"` and are fetched separately from news RSS sources. `mops` sources are fetched via `services/mops_scraper.py`. `website` sources are routed by `_fetch_website_source()` to specialized scrapers (fed, cnyes, worldbank, fsc, caixin, storm, taisounds, linetoday, udn) or a generic web_scraper fallback.

**Two-tier freshness architecture**: Direct RSS/scraper sources provide <1h freshness (Reuters, Bloomberg, Fed, 鉅亨網, 聯合新聞網, 工商時報 livenews, NowNews sitemap, WSJ Markets, Politico Morning Money, etc.). Google News `site:` search sources are now reserved for outlets that fully block direct scraping (IMF — Akamai-blocked) or whose direct feeds are stale/broken (財訊 — wealth.com.tw RSS serves 30 entries with the same stale 4-month-old `pubDate`). Multi-publisher keyword GN searches (e.g. PBOC monetary policy across all outlets) are also kept as GN. All GN `site:` searches use `when:3d` (not `when:7d`) for tighter time windows.

**Scraping limitations**: IMF (`imf.org`) is fully blocked by Akamai Bot Manager (all endpoints return 403) — uses Google News `site:imf.org when:3d` RSS as proxy. 風傳媒 (`storm.mg`) — CloudFront/WAF blocks GCP IP ranges (all paths return 403 from VM, 200 from local), forced back to GN proxy `site:storm.mg when:3d`. 商周 (`businessweekly.com.tw`) — switched to direct RSS `cmsapi.businessweekly.com.tw` (GN proxy no longer needed). 財訊 (`wealth.com.tw`) — `/rss` returns a feed but every entry shares the same 4-month-old `pubDate` (CMS export bug); kept on GN proxy `site:wealth.com.tw when:3d`. Politico's `economy.xml` feed has stagnated (single stale entry) — radar now uses `morningmoney.xml` (daily 8am ET financial-policy newsletter, ~30 entries) instead. WSJ's `feeds.a.dj.com` froze in Jan 2025 — radar now uses `feeds.content.dowjones.io/public/rss/RSSMarketsMain` (>60 fresh entries). UDN financial RSS (`udn.com/rssfeed`) returns valid XML but empty entries — use the category page HTML scraper (`udn.com/news/cate/2/6644` via `udn_scraper.py`) instead. `money.udn.com/rssfeed` works for the finance sub-site.

`MonitorSource.fetch_all` — boolean (default `False`). When `True`, skips keyword filtering so all articles from the source enter the radar; keyword badges are still annotated but only when the full boolean condition matches. Applies to **all source types** including `mops`. Added via `_migrate_db()` `ALTER TABLE`.

`MonitorSource.is_deleted` — boolean (default `False`). Soft delete: when user deletes a source, `is_deleted=True` and `is_active=False` are set instead of row deletion. The URL persists in DB so `_seed_defaults()` / `_migrate_db()` INSERT checks find it and skip re-adding. All MonitorSource queries in `jobs.py`, `settings.py` filter `is_deleted == False`.

`MonitorSource.sort_order` — integer (default `0`). User-controlled display order in SettingsPage; lower = earlier. Initialized from `id` order on first migration. Updated via `PUT /api/settings/sources/reorder` (list of IDs in desired order).

`MonitorSource.fixed_severity` — `VARCHAR`, nullable (default `None`). Dual role as severity floor and source credibility signal: `"critical"` → always critical (skip dynamic); `"high"` → floor high + `source_weight_override=1.6` enabling high keywords to reach critical; `"low"` → floor only. Final severity = `max(floor, dynamic)`. Set via dropdown in SettingsPage expanded source view.

`TopicArticle.add_source`: `"radar"` (added by scheduler) or `"manual"` (added by user search).

`Article` has six extra columns added via `_migrate_db()`: `composite_score`, `finance_relevance`, `novelty_score`, `decay_factor`, `intensity_score` (all `REAL`, nullable, computed by `_compute_article_scores()` in `jobs.py` at save time) + `matched_keyword VARCHAR` (nullable, set from preview data when user saves selected articles via `POST /api/news/save-selected`).

### Frontend Structure

- **Pages:** `RadarPage`, `SearchPage`, `NewsDBPage`, `ReportsPage`, `DashboardPage`, `YouTubePage`, `AnalysisPage`, `FeedbackPage`, `SettingsPage`
- **Responsive layout**: `RadarPage` has separate mobile (`sm:hidden`) and desktop (`hidden sm:flex`) card layouts. Mobile: date+delete on top row, title below full-width, keyword tags limited to 2. Desktop: original horizontal flex (title+article lines in `flex-1`, date+delete on right as `shrink-0`). Global layout: sidebar `hidden md:flex`, mobile bottom tab bar `md:hidden` with "更多" panel for secondary pages.
- **API client:** `frontend/src/services/api.js` — Axios instance with 60s timeout, exports `radarAPI`, `searchAPI`, `newsAPI`, `settingsAPI`, `topicsAPI`, `reportsAPI`, plus `resolveUrl()` utility for Google News redirect resolution. `radarAPI` includes `getNlmReport()` and `getNlmYtReport()` for fetching NLM analysis reports. `copyToClipboard(text)` utility: uses `navigator.clipboard.writeText()` in HTTPS/localhost, falls back to `document.execCommand('copy')` for HTTP (VM) — all copy buttons across pages use this function.
- **Real-time:** `useWebSocket` hook subscribes to backend WebSocket for live alerts.
- **Styling:** Tailwind CSS dark theme, custom classes `card`, `card-hover`, `btn-primary`, `btn-secondary`, `btn-danger`, `input` defined in `index.css`.
- **Severity display** (`NewsDBPage`): `assessSeverity(title, content)` runs client-side with the same keyword lists as the backend. `SeverityBadge` renders text pills (緊急/高/低). Not a server field — computed on render.
- **SettingsPage source list**: drag handle (`⠿`) for drag-to-sort (calls `PUT /sources/reorder`); hover name to reveal inline rename input (Enter/blur saves, Escape cancels). All source types including MOPS have a `fetch_all` toggle and a `fixed_severity` dropdown (動態評估 / 緊急 / 高風險 / 低風險). Keyword category manager uses `CAT_COLORS` (8 colours) — clicking a keyword pill opens a popover to assign it to a named category. Source expanded view includes a type dropdown (RSS / 網頁爬蟲 / 社群) for non-mops/research sources.
- **SettingsPage radar keywords**: Category-based structure — keywords are organized into named categories (`[{name, lang: "tw"|"en", keywords: [...]}]`), stored in `SystemConfig["radar_topic_categories"]` via `GET/PUT /api/settings/radar-topic-categories`. On save, TW categories flatten to `radar_topics`, EN categories to `radar_topics_us`. Each category renders as a coloured card (`CAT_COLORS`, 8 colours) with TW/EN badge; simple keywords as pills, boolean combos via `GroupedKeywordCard`. Backward-compatible: old flat lists auto-migrate to a single "未分類" category on load. `stripNotTerms(kw)` extracts `NOT term` / `NOT "multi word"` clauses from boolean keyword strings; `serializeGroups(groups, notTerms)` appends them at the end. Boolean keyword cards show NOT terms as red chips; the edit panel has a dedicated "排除詞（NOT）" input section. Global exclusion keywords are managed in a red-bordered section below the categories — saved alongside topics via `updateRadarTopics(..., exclusion_keywords)`. `parseGroupedKeyword(kw)` calls `stripNotTerms` before regex parsing so NOT clauses don't break group detection.
- **AnalysisPage** (`/analysis`): Two tabs (新聞分析 / YouTube 影片分析). History row (horizontal scroll) lets users select past reports by date. `renderReport()` renders Markdown headings, dividers, bold text; `renderInline()` handles `**bold**` and URLs in the same line; `linkify()` converts bare URLs to `<a>` links. Shows `generated_at` timestamp and `source_title` metadata. Empty state shown when no report exists. All `generated_at` timestamps are tagged with `Z` by `_iso_utc()` in `radar.py` so JavaScript interprets them as UTC, not local time.
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
| `/api/radar` | `routers/radar.py` | Alerts CRUD, market data, watchlist, signal conditions. NLM: `POST/GET /notebooklm-report`, `POST/GET /notebooklm-yt-report`. Gemini: `GET /gemini-report`, `GET /gemini-yt-report`, `GET /gemini-reports?report_type=`, `GET /gemini-reports/{id}`, `POST /gemini-analyze` (manual trigger). All stored in `NlmReport` table + `SystemConfig`. |
| `/api/search` | `routers/search.py` | Topic search, AI analysis, positions |
| `/api/news` | `routers/news_db.py` | Article CRUD, fetch preview, save-selected, sentiment. `POST /fetch` supports `source_type`: `"sources_only"` (RSS + website sources, default) or `"gn_only"` (Google News). When no query, uses radar_topics + active Topic keywords. Query strings are split via `_split_query_terms()` (spaces + ASCII/CJK boundary) for OR matching. Boolean topics dispatched via `_gn_fetch_topic()` → `_multi_search_topic`. `GET /sources` returns configured source names + `__other__` with counts; `GET /keywords` returns unique `matched_keyword` values with counts. `GET /articles` accepts `source` and `keyword` query params for filtering. |
| `/api/topics` | `routers/topics.py` | Topic CRUD, per-topic articles, Google News search+import |
| `/api/research` | `routers/research.py` | Research institutions, reports CRUD, fetch preview, save-selected |
| `/api/youtube` | `routers/youtube.py` | YouTube channel CRUD, video fetch, mark-as-seen |
| `/api/line/webhook` | `routers/line_webhook.py` | LINE Bot webhook receiver (POST only, signature-verified) |
| `/api/settings` | `routers/settings.py` | Monitor sources (including `fetch_all`, `sort_order` fields), notifications, Google Sheets, AI model config, finance filter toggle+threshold, RSS priority threshold, GN critical-only toggle, radar exclusion keywords. `PUT /sources/reorder` — bulk sort_order update (list of IDs, must be registered **before** `PUT /sources/{id}` to avoid FastAPI routing conflict). `POST /sources/{id}/test-rss` supports all types: `mops`, `website` (dispatches to fed/cnyes/worldbank/fsc/caixin/storm/taisounds/linetoday/udn scrapers via same `is_*_url()` routing), and `rss`/`social`. `GET /radar-topics` response includes `exclusion_keywords` field; `PUT /radar-topics` accepts it. |
| `/api/feedback` | `routers/feedback.py` | User feedback CRUD (GET list, POST create, DELETE by id) |
| `/api/utils/resolve-url` | `main.py` | Follow redirects, return final article URL (used by copy buttons) |
| `/api/utils/resolve-stored-urls` | `main.py` | One-time background job: resolve all Google News redirect URLs in DB |
| `/ws` | `main.py` | WebSocket for real-time broadcasts |

## NotebookLM Local Automation (`scripts/notebooklm_hourly.py`)

Runs on the **local Windows machine** via Task Scheduler (not on the VM). Requires `pip install notebooklm-py requests beautifulsoup4` and `notebooklm login` (browser-based auth, saves to `~/.notebooklm/storage_state.json`; re-run when auth expires).

The script handles **two separate notebooks**: news analysis (`NOTEBOOK_ID`) and YouTube analysis (`NOTEBOOK_ID_YT`). Each is an independent flow run sequentially in the same script invocation.

**Skill sources** (`scripts/skills/`): Permanent `.md` files (analysis team framework) loaded into each notebook once and never deleted. Identified by `[SKILL] ` title prefix. `_ensure_skill_sources(client, notebook_id)` lists existing sources, adds any missing `[SKILL]*` files; `_cleanup_news_sources(client, notebook_id)` deletes all non-`[SKILL]` sources before each run (removes stale news while keeping framework intact).

**State tracking**: `.nlm_state.json` stores `news_last_run` and `yt_last_run` (separate ISO timestamps). On each run, if the gap since last run exceeds `HOURS_BACK`, the script fetches from that timestamp (catchup mode). Manual runs with `--hours`/`--since` flags do NOT update state; all other runs do.

**News analysis flow**:
1. Step 0: `_ensure_skill_sources()` then `_cleanup_news_sources()` to reset news sources
2. Fetch articles from `GET /api/news/articles?limit=500&fetched_after=<cutoff>` → client-side severity filter
3. `_add_source_with_fallback(client, notebook_id, url, title, requests)` for each article: tries `add_url(wait=False)` first; on failure, fetches page HTML and `add_text()` as fallback
4. `add_text(NOTEBOOK_ID, summary_md, wait=True)` — full article list with metadata
5. `generate_report(ReportFormat.CUSTOM, language="zh-TW", custom_prompt=_build_news_prompt(len(articles)))`
6. `wait_for_completion(NOTEBOOK_ID, task_id, timeout=300)`
7. `download_report(...)` → saves to `scripts/nlm_reports/YYYYMMDD_HHMM.md`
8. `POST /api/radar/notebooklm-report` → pushes to VM

**`_build_news_prompt(article_count)`** selects one of two prompt versions based on article count. Both versions use the full analysis team framework (references `[SKILL] PROJECT_INSTRUCTIONS_v2` and `[SKILL] SKILL_*`). Output format is identical for both:
- `< 10` articles → max **1 category**; `≥ 10` articles → max **2 categories**
- Fixed 3-point structure per category: `1. **事件描述**` / `2. **市場與國別影響**` / `3. **後續分析**`
- Footer: `### 關鍵來源` with `- 一-1. 標題（URL）` per point

**YouTube analysis flow**:
1. Step 0: `_ensure_skill_sources()` then `_cleanup_news_sources()` on `NOTEBOOK_ID_YT`
2. `_is_youtube_short(video_id, requests)` — HEAD `/shorts/{id}`, 200 → Short (add with 1 analysis point only)
3. Fetch and add video URLs via `_add_source_with_fallback`; max 15 videos
4. `generate_report(...)` with `custom_prompt`: per-video `一、【頻道名稱】影片標題`; Shorts get 1 point, regular videos get 3; same team framework reference
5. Download and push to `POST /api/radar/notebooklm-yt-report`

**CLI flags**: `--hours N`, `--since "MM/DD HH:MM"` (Taiwan time), `--severity critical|high`, `--news-only`, `--yt-only`, `--no-save-state`. Manual `--hours`/`--since` use `published_at` filter for YT (not `is_new` flag).

Config in `scripts/.env.local` (copy from `scripts/.env.local.example`): `API_BASE_URL=http://34.23.154.194` (VM IP, no port — nginx proxy), `NOTEBOOK_ID`, `NOTEBOOK_ID_YT`, `HOURS_BACK=3` (matches 3-hour Task Scheduler interval), `MIN_SEVERITY=low`, `RESULT_PUSH_LINE`.

**notebooklm-py 0.3.4 API**: `async with await NotebookLMClient.from_storage() as client:` — note the double `await`. Sub-clients:
- `client.sources` — `add_text`, `add_url(wait=False for async)`, `add_file`, `list(notebook_id)`, `delete(notebook_id, source_id)`
- `client.artifacts` — `generate_report(report_format, language, custom_prompt)`, `wait_for_completion(notebook_id, task_id, timeout)`, `download_report(notebook_id, output_path, artifact_id)`. `ReportFormat` values: `BRIEFING_DOC`, `STUDY_GUIDE`, `BLOG_POST`, `CUSTOM`.
- `client.chat` — `ask` → `AskResult.answer` (use for Q&A, not for structured reports)
- `client.notebooks` — `list`, `create`, `get`

**Cookie refresh** (`_refresh_cookies_playwright()`): Before each run, opens `notebooklm.google.com` via Playwright **headed** (not headless — Google blocks headless Chromium with redirect to login page). Loads existing `storage_state.json`, waits 3s for short-lived `__Secure-*PSIDRTS` cookies to refresh, saves back. Runs in a separate thread with `ProactorEventLoop` (Playwright requirement on Windows) to avoid conflict with the main `SelectorEventLoop`. If refresh fails, script still attempts `NotebookLMClient.from_storage()` — may work if cookies haven't fully expired yet.

**Safe print wrapper**: Global `print()` is overridden to catch `OSError: [Errno 22]` — Windows Task Scheduler runs without a console, causing stdout writes to fail. The wrapper silently drops output on pipe errors; all important messages also go through `_log` (FileHandler to `nlm_reports/run.log`).

**`--cookie-refresh` mode**: Lightweight flag that only runs `_refresh_cookies_playwright()` then exits. Used by a separate Task Scheduler task "NLM Cookie KeepAlive" every 45 minutes to keep `__Secure-*PSIDRTS` cookies alive between 3-hour analysis runs (PSIDRTS cookies expire in seconds; 3-hour gaps consistently cause auth failure).

## Gemini Auto-Analysis (`backend/services/gemini_analysis.py`)

Runs on the **VM** via APScheduler (every 3 hours, first run 5 min after startup). Uses Gemini API directly — no local machine dependency.

**Two analysis jobs** in one scheduler entry (`gemini_analysis` in `jobs.py`):
1. `run_gemini_news_analysis(hours_back=3)` — queries `Article` table for recent articles, filters by severity, builds prompt with analyst roundtable framework, saves to `NlmReport(report_type="gemini_news")` + `SystemConfig["gemini_latest_report"]`
2. `run_gemini_yt_analysis(hours_back=3)` — queries `YoutubeVideo` table, same flow, saves as `report_type="gemini_yt"` + `SystemConfig["gemini_yt_latest_report"]`

**Cooldown guard** (in `scheduler/jobs.py`): Before running, reads `gemini_report_generated_at` from `SystemConfig`; skips if < 2.5 hours elapsed — prevents repeated triggers on `--reload` service restarts.

**Retry mechanism** (`_call_gemini_with_retry`): 503 (model overload) and 429 (quota exhausted) trigger automatic retry with backoff delays of 30s → 60s → 120s, up to 3 retries. `gemini-2.5-flash` free tier has a 20 requests/day limit.

**Auto-shrink**: If article count exceeds 120, automatically filters to `high`+ severity only to stay within token limits.

**`_iso_utc()` in `radar.py`**: All NlmReport datetime fields are serialized via `_iso_utc(dt)` which appends `Z` if absent — ensures JavaScript interprets the timestamp as UTC, not local time (SQLite stores naive UTC datetimes that `isoformat()` would return without timezone marker).

**`youtube_feed.py` UTC fix**: `_parse_published()` uses `calendar.timegm()` (not `time.mktime()`) to convert `published_parsed` struct from feedparser — feedparser returns UTC structs, `mktime()` would treat them as local time causing an 8-hour offset. `_video_dict()` in `youtube.py` also appends `Z` to `isoformat()` output for the same reason.
