"""APScheduler jobs for radar scanning and daily news collection."""

import asyncio
import hashlib
import json
import logging
import os
import re
import traceback
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.exc import IntegrityError

from backend.config import settings
from backend.database import (
    Alert,
    Article,
    MarketWatchItem,
    MonitorSource,
    NotificationSetting,
    ResearchReport,
    SessionLocal,
    SignalCondition,
    SystemConfig,
)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
_ws_manager = None
_scan_lock = asyncio.Lock()  # prevents concurrent radar scans within same process

# 使用絕對路徑避免 CWD 問題
_DEBUG_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "notification_debug.log")
_DEBUG_LOG_PATH = os.path.normpath(_DEBUG_LOG_PATH)


def _flog(msg: str):
    """寫入檔案日誌（不受 uvicorn --reload 影響）。"""
    try:
        os.makedirs(os.path.dirname(_DEBUG_LOG_PATH), exist_ok=True)
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.utcnow().isoformat()} {msg}\n")
    except Exception:
        pass


def start_scheduler(ws_manager):
    """Start the APScheduler with all jobs."""
    global _ws_manager
    _ws_manager = ws_manager

    # 從 DB 讀取使用者設定的掃描間隔（避免 --reload 覆蓋使用者設定）
    radar_interval = settings.RADAR_INTERVAL_MINUTES  # .env fallback
    try:
        db = SessionLocal()
        row = db.query(SystemConfig).filter(SystemConfig.key == "radar_interval_minutes").first()
        if row:
            radar_interval = max(1, min(int(row.value), 60))
        db.close()
    except Exception:
        pass

    _flog(f"[STARTUP] Scheduler starting, radar_interval={radar_interval}min, log={_DEBUG_LOG_PATH}")

    from datetime import timedelta

    # First run after 3 minutes — gives old --reload process time to die fully,
    # preventing the race condition where two processes both scan at startup.
    first_run = datetime.utcnow() + timedelta(minutes=3)

    # Radar scan every N minutes (使用 DB 儲存的間隔，非 .env)
    scheduler.add_job(
        radar_scan,
        "interval",
        minutes=radar_interval,
        id="radar_scan",
        name="即時偵測雷達掃描",
        next_run_time=first_run,
    )

    # Daily news collection at configured time
    scheduler.add_job(
        daily_news_fetch,
        "cron",
        hour=settings.NEWS_SCHEDULE_HOUR,
        minute=settings.NEWS_SCHEDULE_MINUTE,
        id="daily_news",
        name="每日新聞蒐集",
    )

    # Daily research report collection at 10:00
    scheduler.add_job(
        daily_research_fetch,
        "cron",
        hour=10,
        minute=0,
        id="daily_research",
        name="每日研究報告蒐集",
    )

    # Market data refresh every hour (or configured interval)
    scheduler.add_job(
        market_check,
        "interval",
        minutes=settings.MARKET_CHECK_INTERVAL_MINUTES,
        id="market_check",
        name="市場指標檢查",
        next_run_time=first_run,
    )

    # YouTube channel check every 30 minutes
    scheduler.add_job(
        youtube_check,
        "interval",
        minutes=30,
        id="youtube_check",
        name="YouTube 頻道新影片偵測",
        next_run_time=first_run,
    )

    scheduler.start()
    logger.info("Scheduler started with radar and daily news jobs")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


async def radar_scan(force: bool = False):
    """Main radar scan job - checks all sources for new signals.

    Flow: Fetch news → match position exposure → create alert (no AI) → notify

    force=True: 手動觸發，跳過 240 秒跨進程鎖但仍更新 lock timestamp，
                讓 scheduler 下次運行等足夠時間，避免雙重掃描。
    """
    _flog(f"[SCAN] radar_scan() called force={force} lock={_scan_lock.locked()}")
    if _scan_lock.locked():
        if not force:
            _flog("[SCAN] Skipped: lock held, not force")
            logger.info("Radar scan already running, skipping concurrent trigger")
            return
        # Force scan: 等待正在進行的掃描完成後再執行（最多等 90 秒）
        logger.info("Force scan: 正在等待目前掃描完成...")

    # Cross-process guard: with --reload, multiple uvicorn processes can each run their
    # own scheduler. Use a DB timestamp to prevent two processes scanning within 4 minutes.
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        lock_rec = db.query(SystemConfig).filter(SystemConfig.key == "radar_scan_lock").first()
        if not force:
            # Auto scan: enforce the 240-second cooldown
            if lock_rec:
                try:
                    last = datetime.fromisoformat(lock_rec.value)
                    if (now - last).total_seconds() < 240:
                        _flog(f"[SCAN] Skipped: cross-process lock, {(now - last).total_seconds():.0f}s ago")
                        logger.info(f"Radar scan skipped (cross-process lock): last scan {(now - last).total_seconds():.0f}s ago")
                        return
                except (ValueError, TypeError):
                    pass
        # Both force and auto scans update the lock timestamp
        if lock_rec:
            lock_rec.value = now.isoformat()
        else:
            db.add(SystemConfig(key="radar_scan_lock", value=now.isoformat()))
        db.commit()
    except Exception as e:
        logger.warning(f"Cross-process lock check failed (non-fatal): {e}")
    finally:
        db.close()

    async with _scan_lock:
        await _radar_scan_inner(force=force)


async def _fetch_website_source(url: str, hours_back: int = 24) -> list[dict]:
    """Fetch articles from a website/API source.

    Routing logic:
    - 鉅亨網 JSON API (api.cnyes.com) → cnyes_scraper
    - World Bank API (search.worldbank.org) → worldbank_scraper
    - 金管會 FSC (fsc.gov.tw) → fsc_scraper
    - 財新 Caixin (caixinglobal.com) → caixin_scraper
    - Other URLs → generic web_scraper (single-page scrape)
    """
    from backend.services.cnyes_scraper import is_cnyes_api_url, fetch_cnyes_from_url
    from backend.services.worldbank_scraper import is_worldbank_api_url, fetch_worldbank_news
    from backend.services.fsc_scraper import is_fsc_url, fetch_fsc_news
    from backend.services.caixin_scraper import is_caixin_url, fetch_caixin_news
    from backend.services.storm_scraper import is_storm_url, fetch_storm_news
    from backend.services.taisounds_scraper import is_taisounds_url, fetch_taisounds_news
    from backend.services.linetoday_scraper import is_linetoday_url, fetch_linetoday_news
    from backend.services.udn_scraper import is_udn_cate_url, fetch_udn_cate_news
    from backend.services.web_scraper import scrape_page

    if is_cnyes_api_url(url):
        return await fetch_cnyes_from_url(url, hours_back)
    if is_worldbank_api_url(url):
        return await fetch_worldbank_news(url, hours_back)
    if is_fsc_url(url):
        return await fetch_fsc_news(hours_back)
    if is_caixin_url(url):
        return await fetch_caixin_news(hours_back)
    if is_storm_url(url):
        return await fetch_storm_news(hours_back)
    if is_taisounds_url(url):
        return await fetch_taisounds_news(hours_back)
    if is_linetoday_url(url):
        return await fetch_linetoday_news(hours_back)
    if is_udn_cate_url(url):
        return await fetch_udn_cate_news(url, hours_back)

    # Generic HTML scraping — returns at most one article (the page itself)
    result = await scrape_page(url)
    if result.get("title") and result.get("content"):
        return [result]
    return []


async def _radar_scan_inner(force: bool = False):
    from backend.services import rss_feed
    from backend.services.google_news import search_google_news
    from backend.services.exposure import format_exposure_summary, match_positions_to_news
    from backend.services.google_sheets import get_positions

    logger.info("Running radar scan...")
    _flog(f"[SCAN] === Radar scan START force={force} ===")
    db = SessionLocal()

    try:
        # Load user-configured severity keywords (falls back to defaults)
        from backend.routers.settings import get_severity_keywords as _load_sev_kw, get_severity_rules as _load_sev_rules
        _sev_crit, _sev_high = _load_sev_kw(db)
        _sev_rules = _load_sev_rules(db)

        # 時間衰減閾值（小時）
        _decay_cfg = db.query(SystemConfig).filter(SystemConfig.key == "severity_decay_hours").first()
        _decay_hours = int(_decay_cfg.value) if _decay_cfg else 6

        # Load hours_back early — shared by RSS (step 1) and Google News (step 2)
        hours_config = db.query(SystemConfig).filter(SystemConfig.key == "radar_hours_back").first()
        gn_hours_back = int(hours_config.value) if hours_config else 24

        # Load radar topics early to build global keyword fallback for RSS sources
        # (also reused by Google News step 2 to avoid a second DB query)
        _tw_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_topics").first()
        _all_tw_topics = json.loads(_tw_cfg.value) if _tw_cfg else ["金融", "股市", "經濟"]
        _us_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_topics_us").first()
        _all_us_topics = json.loads(_us_cfg.value) if _us_cfg else []
        # Combined topic list passed to RSS filter as global fallback (boolean semantics preserved)
        _global_topics = _all_tw_topics + _all_us_topics
        # RSS-only mode: skip all Google News fetching
        _rss_only_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_rss_only").first()
        _rss_only = (_rss_only_cfg.value == "true") if _rss_only_cfg else False

        # RSS 優先模式：RSS 文章數 >= 門檻時跳過 Google News
        _rss_min_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_rss_min_articles").first()
        _rss_min_articles = int(_rss_min_cfg.value) if _rss_min_cfg and _rss_min_cfg.value.isdigit() else 0
        # 0 表示停用 RSS 優先（預設行為）

        # Google News 僅保留緊急設定
        _gn_crit_cfg = db.query(SystemConfig).filter(SystemConfig.key == "gn_critical_only").first()
        _gn_critical_only = (_gn_crit_cfg.value == "true") if _gn_crit_cfg else False

        # 全域排除關鍵字（匹配即丟棄文章）
        _excl_kw_cfg = db.query(SystemConfig).filter(SystemConfig.key == "radar_exclusion_keywords").first()
        try:
            _exclusion_kws = json.loads(_excl_kw_cfg.value) if _excl_kw_cfg else []
        except Exception:
            _exclusion_kws = []

        # 財經相關性篩選設定
        _fin_filter_cfg = db.query(SystemConfig).filter(SystemConfig.key == "finance_filter_enabled").first()
        _fin_filter_enabled = (_fin_filter_cfg.value == "true") if _fin_filter_cfg else False
        _fin_threshold_cfg = db.query(SystemConfig).filter(SystemConfig.key == "finance_relevance_threshold").first()
        try:
            _fin_threshold = float(_fin_threshold_cfg.value) if _fin_threshold_cfg else 0.15
        except (ValueError, TypeError):
            _fin_threshold = 0.15

        # 建立已知來源名稱集合（用於 GN 文章可信度懲罰：來源不在此清單者 weight=0.65）
        # 同時建立固定風險等級 map（source_name → fixed_severity）
        _all_ms = db.query(MonitorSource).filter(MonitorSource.is_active == True).all()
        _ksn: set = set()
        _source_fixed_sev: dict = {}
        for _ms in _all_ms:
            if _ms.name:
                _clean = re.sub(r'\s*[\(（].*?[\)）]', '', _ms.name).strip().lower()
                if _clean:
                    _ksn.add(_clean)
            if _ms.fixed_severity and _ms.name:
                _source_fixed_sev[_ms.name] = _ms.fixed_severity
        _known_source_names: frozenset = frozenset(_ksn)

        def _article_severity(a: dict) -> str:
            """取得文章風險等級：優先使用來源固定等級，否則動態評估。"""
            src = a.get("source", "")
            if src and src in _source_fixed_sev:
                return _source_fixed_sev[src]
            return _assess_severity_single(a, _sev_crit, _sev_high, _sev_rules, _decay_hours, _known_source_names)

        # 1. Fetch from active RSS sources (includes social type = Nitter/RSS mirrors)
        sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type.in_(["rss", "social"]),
        ).all()

        feeds = [
            {
                "name": s.name,
                "url": s.url,
                "keywords": json.loads(s.keywords) if s.keywords else [],
                "fetch_all": bool(getattr(s, "fetch_all", False)),
            }
            for s in sources
        ]

        new_articles = []
        seen_urls = set()
        seen_titles = set()
        seen_content_fps: list = []   # 內容相似度 fingerprint 清單（跨步驟共享）

        _raw_rss_articles: list[dict] = []  # unfiltered RSS pool for topic cross-matching
        if feeds:
            rss_results, _raw_rss_articles = await rss_feed.fetch_multiple_feeds(
                feeds, hours_back=gn_hours_back, global_topics=_global_topics, return_raw=True
            )
            _rss_skip_empty = 0
            _rss_skip_seen = 0
            _rss_skip_db_url = 0
            _rss_skip_db_title = 0
            _rss_skip_dup = 0
            for article_data in rss_results:
                url = article_data.get("source_url", "")
                title = article_data.get("title", "").strip()
                if not url or not title:
                    _rss_skip_empty += 1
                    continue
                if url in seen_urls or title in seen_titles:
                    _rss_skip_seen += 1
                    continue
                if not force:
                    if db.query(Article).filter(Article.source_url == url).first():
                        _rss_skip_db_url += 1
                        continue
                    if db.query(Article).filter(Article.title == title).first():
                        _rss_skip_db_title += 1
                        continue
                fp = _article_fingerprint(title, article_data.get("content", ""))
                if _is_content_duplicate(fp, seen_content_fps):
                    _rss_skip_dup += 1
                    continue
                seen_urls.add(url)
                seen_titles.add(title)
                seen_content_fps.append(fp)
                article_data['from_rss'] = True
                new_articles.append(article_data)
            _flog(f"[SCAN] RSS: {len(rss_results)} fetched, {len(new_articles)} new "
                  f"(skip: empty={_rss_skip_empty} seen={_rss_skip_seen} db_url={_rss_skip_db_url} "
                  f"db_title={_rss_skip_db_title} dup={_rss_skip_dup})")

        # 1b. Fetch MOPS 公開資訊觀測站重大訊息（type="mops" 來源啟用時）
        mops_source = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "mops",
        ).first()
        if mops_source:
            try:
                from backend.services.mops_scraper import fetch_mops_material_news
                from backend.services.rss_feed import (
                    _filter_by_keywords as _kw_filter,
                    _filter_by_topic_strings as _tp_filter,
                    _annotate_matched_terms as _ann,
                )
                mops_articles = await fetch_mops_material_news(hours_back=gn_hours_back)
                mops_kws = json.loads(mops_source.keywords) if mops_source.keywords else []
                mops_fetch_all = bool(getattr(mops_source, "fetch_all", False))
                if mops_fetch_all:
                    mops_articles = [
                        {**a, "matched_keyword": _ann(a, mops_kws) if mops_kws else "", "fetch_all_source": True}
                        for a in mops_articles
                    ]
                elif mops_kws:
                    mops_articles = _kw_filter(mops_articles, mops_kws)
                elif _global_topics:
                    mops_articles = _tp_filter(mops_articles, _global_topics)
                else:
                    mops_articles = []
                for article_data in mops_articles:
                    url = article_data.get("source_url", "")
                    title = article_data.get("title", "").strip()
                    if url and title and url not in seen_urls and title not in seen_titles:
                        if force or (
                            not db.query(Article).filter(Article.source_url == url).first() and
                            not db.query(Article).filter(Article.title == title).first()
                        ):
                            seen_urls.add(url)
                            seen_titles.add(title)
                            new_articles.append(article_data)
            except Exception as mops_err:
                logger.warning(f"MOPS fetch error (non-fatal): {mops_err}")

        # 1c. Fetch website/API sources (type="website"): JSON API 或 HTML 爬蟲
        website_sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "website",
        ).all()
        if website_sources:
            from backend.services.rss_feed import (
                _filter_by_keywords as _kw_filter,
                _filter_by_topic_strings as _tp_filter,
            )
            for ws in website_sources:
                try:
                    ws_fetch_all = bool(getattr(ws, 'fetch_all', False))
                    # fetch_all 來源：用 48h 底限，確保 API 返回的所有精選文章都能通過時間過濾
                    # 一般來源：用 max(hours_back, 3h) 作小緩衝，防止短暫中斷造成漏抓
                    ws_hours_back = max(gn_hours_back, 48) if ws_fetch_all else max(gn_hours_back, 3)
                    ws_articles = await _fetch_website_source(ws.url, ws_hours_back)
                    ws_kws = json.loads(ws.keywords) if ws.keywords else []
                    if ws_fetch_all:
                        # 全文讀取：納入全部，用 _annotate_matched_terms 標記實際出現的所有關鍵詞
                        # 標記 fetch_all_source 讓財經篩選跳過這些文章（但仍計算分數）
                        if ws_kws:
                            from backend.services.rss_feed import _annotate_matched_terms as _ann
                            ws_articles = [
                                {**a, "matched_keyword": _ann(a, ws_kws), "fetch_all_source": True}
                                for a in ws_articles
                            ]
                        else:
                            ws_articles = [{**a, "fetch_all_source": True} for a in ws_articles]
                    elif ws_kws:
                        ws_articles = _kw_filter(ws_articles, ws_kws)
                    elif _global_topics:
                        ws_articles = _tp_filter(ws_articles, _global_topics)
                    else:
                        ws_articles = []
                    for article_data in ws_articles:
                        url = article_data.get("source_url", "")
                        title = article_data.get("title", "").strip()
                        if url and title and url not in seen_urls and title not in seen_titles:
                            if force or (not db.query(Article).filter(Article.source_url == url).first() and \
                               not db.query(Article).filter(Article.title == title).first()):
                                fp = _article_fingerprint(title, article_data.get("content", ""))
                                if _is_content_duplicate(fp, seen_content_fps):
                                    continue
                                seen_urls.add(url)
                                seen_titles.add(title)
                                seen_content_fps.append(fp)
                                new_articles.append(article_data)
                except Exception as ws_err:
                    logger.warning(f"Website source fetch error ({ws.url}): {ws_err}")

        # 2. Fetch latest headlines via Google News RSS — TW + US topics in parallel
        # 跳過條件：RSS-only 模式，或 RSS 優先模式且 RSS 文章數已達門檻
        _rss_collected = sum(1 for a in new_articles if a.get('from_rss'))
        _skip_gn = _rss_only or (
            _rss_min_articles > 0 and not force and _rss_collected >= _rss_min_articles
        )
        if _skip_gn and not _rss_only:
            _flog(f"[SCAN] RSS 優先：已蒐集 {_rss_collected} 篇（>= {_rss_min_articles}），跳過 Google News")
        if not _skip_gn:
            topics = _all_tw_topics
            us_topics = _all_us_topics
            # gn_hours_back already loaded above (shared with RSS step)
            # force 掃描使用較短回溯時窗（2h）以顯示近期新聞；自動掃描使用使用者設定值
            gn_hours = min(2, gn_hours_back) if force else gn_hours_back

            _b_semaphore = asyncio.Semaphore(_RADAR_CONCURRENCY)

            async def _fetch_radar_topic(topic: str, lang: str = "zh-TW", country: str = "TW") -> tuple[str, list[dict]]:
                # 兼容舊版 [en-US] suffix（新版改用 us_topics 區塊，此處僅作向後相容）
                clean_topic = topic
                _m = re.search(r'\[([a-z]{2})-([A-Z]{2})\]\s*$', topic)
                if _m:
                    lang = _m.group(1)
                    country = _m.group(2)
                    clean_topic = topic[:_m.start()].strip()

                async with _b_semaphore:
                    try:
                        if '(' in clean_topic:
                            results = await _multi_search_topic([clean_topic], hours_back=gn_hours)
                        else:
                            results = await search_google_news(
                                query=clean_topic, hours_back=gn_hours, max_results=20,
                                language=lang, country=country,
                            )
                        return topic, results
                    except Exception:
                        return topic, []

            # 台灣區（中文）+ 英文美國區 — 全部並行
            topic_batches = await asyncio.gather(
                *[_fetch_radar_topic(t, "zh-TW", "TW") for t in topics],
                *[_fetch_radar_topic(t, "en", "US") for t in us_topics],
            )

            for topic, headlines in topic_batches:
                for article_data in headlines:
                    url = article_data.get("source_url", "")
                    title = article_data.get("title", "").strip()
                    if url and title and url not in seen_urls and title not in seen_titles:
                        if force or (not db.query(Article).filter(Article.source_url == url).first() and \
                           not db.query(Article).filter(Article.title == title).first()):
                            fp = _article_fingerprint(title, article_data.get("content", ""))
                            if _is_content_duplicate(fp, seen_content_fps):
                                continue
                            seen_urls.add(url)
                            seen_titles.add(title)
                            seen_content_fps.append(fp)
                            article_data['matched_keyword'] = _extract_matched_terms(topic, title, article_data.get("content", ""))
                            article_data['origin'] = 'gn'
                            # GN 僅緊急模式：預先評估嚴重度，非緊急文章丟棄
                            if _gn_critical_only:
                                _pre_sev = _article_severity(article_data)
                                if _pre_sev != "critical":
                                    seen_urls.discard(url)
                                    seen_titles.discard(title)
                                    seen_content_fps.pop()
                                    continue
                            new_articles.append(article_data)

        # 3b. Topic-specific searches — results feed BOTH radar alerts and TopicArticle.
        # Two passes per topic:
        #   Pass A: cross-match articles already collected in Steps 1+2 (RSS / general GN).
        #           These articles are new to the DB, so if they match a topic keyword they
        #           belong in TopicArticle even though they weren't found by a topic GN search.
        #   Pass B: dedicated Google News search using topic keywords (hours_back=3 to avoid
        #           the gap that hours_back=1 caused — articles 1-3h old were never picked up).
        from backend.database import Topic as TopicModel, TopicArticle
        active_topics = db.query(TopicModel).filter(TopicModel.is_active == True).all()
        topic_articles_to_save: list[tuple] = []  # (topic_id, article_dict) deferred until after commit
        # 記憶體內去重：防止同一次掃描的 Pass A / Pass B 重複加入相同文章
        _queued_topic_urls: dict[int, set] = {}  # topic_id -> set of source_urls already queued

        # Snapshot of articles from Steps 1+2 before Step 3b adds more
        rss_gn_articles = list(new_articles)

        for topic in active_topics:
            kws = json.loads(topic.keywords) if topic.keywords else []
            if not kws:
                continue
            groups = _parse_keyword_groups(kws)
            queued_urls = _queued_topic_urls.setdefault(topic.id, set())

            # Pass A: cross-match RSS / general-GN articles against this topic's keywords
            for a in rss_gn_articles:
                url = a.get("source_url", "")
                if not url or url in queued_urls:
                    continue
                text = f"{a.get('title', '')} {a.get('content', '')}".lower()
                if not _match_keyword_groups(text, groups):
                    continue
                if not db.query(TopicArticle).filter_by(topic_id=topic.id, source_url=url).first():
                    queued_urls.add(url)
                    topic_articles_to_save.append((topic.id, a))
                    logger.debug(f"Topic '{topic.name}' ← RSS/GN: {a.get('title','')[:60]}")

            # Pass A2: RSS-only 模式下，對未過濾的 raw RSS 文章做主題比對
            # 補上「符合主題關鍵字但未符合雷達關鍵字」的文章，帶進雷達 + 主題頁
            if _skip_gn and _raw_rss_articles:
                for a in _raw_rss_articles:
                    url = a.get("source_url", "")
                    title = a.get("title", "").strip()
                    if not url or not title or url in seen_urls or title in seen_titles:
                        continue
                    text = f"{title} {a.get('content', '')}".lower()
                    if not _match_keyword_groups(text, groups):
                        continue
                    # New article matching topic keywords — add to radar + topic
                    if force or (not db.query(Article).filter(Article.source_url == url).first() and
                                 not db.query(Article).filter(Article.title == title).first()):
                        fp = _article_fingerprint(title, a.get("content", ""))
                        if _is_content_duplicate(fp, seen_content_fps):
                            continue
                        seen_urls.add(url)
                        seen_titles.add(title)
                        seen_content_fps.append(fp)
                        a_copy = dict(a)
                        a_copy['matched_keyword'] = _extract_matched_terms(kws, title, a.get("content", ""))
                        a_copy['from_rss'] = True
                        new_articles.append(a_copy)
                        if url not in queued_urls and not db.query(TopicArticle).filter_by(topic_id=topic.id, source_url=url).first():
                            queued_urls.add(url)
                            topic_articles_to_save.append((topic.id, a_copy))
                        logger.debug(f"Topic '{topic.name}' ← raw RSS (A2): {title[:60]}")

            # Pass B: dedicated Google News search for this topic
            # Skipped when RSS-only mode is enabled, or RSS priority threshold met
            if _skip_gn:
                continue
            # force 掃描用 2h（顯示近期），自動掃描用 3h（避免 1h 間隔遺漏文章）
            try:
                topic_results = await _multi_search_topic(kws, hours_back=2 if force else 6)
            except Exception as e:
                logger.warning(f"Topic '{topic.name}' Google News search error: {e}")
                continue

            for a in topic_results:
                text = f"{a.get('title', '')} {a.get('content', '')}".lower()
                if not _match_keyword_groups(text, groups):
                    continue
                url = a.get("source_url", "")
                title = a.get("title", "").strip()
                if not url or url in queued_urls:
                    continue

                # Queue for TopicArticle (deduped per topic, in-memory + DB check)
                if not db.query(TopicArticle).filter_by(topic_id=topic.id, source_url=url).first():
                    queued_urls.add(url)
                    topic_articles_to_save.append((topic.id, a))

                # Also merge into new_articles for radar alert
                if url not in seen_urls and title not in seen_titles:
                    if force or (not db.query(Article).filter(Article.source_url == url).first() and \
                       not db.query(Article).filter(Article.title == title).first()):
                        fp = _article_fingerprint(title, a.get("content", ""))
                        if not _is_content_duplicate(fp, seen_content_fps):
                            seen_urls.add(url)
                            seen_titles.add(title)
                            seen_content_fps.append(fp)
                            a_copy = dict(a)
                            a_copy['matched_keyword'] = _extract_matched_terms(kws, title, a.get("content", ""))
                            a_copy['origin'] = 'gn'
                            # GN 僅緊急模式：預先評估嚴重度，非緊急文章不進雷達（仍存入主題頁）
                            if _gn_critical_only:
                                _pre_sev = _article_severity(a_copy)
                                if _pre_sev != "critical":
                                    seen_urls.discard(url)
                                    seen_titles.discard(title)
                                    seen_content_fps.pop()
                                    continue
                            new_articles.append(a_copy)
                            logger.debug(f"Topic '{topic.name}' → radar: {title[:60]}")

        # 全域排除關鍵字過濾（匹配任一關鍵字即丟棄）
        if _exclusion_kws:
            from backend.services.rss_feed import _term_in_text as _rss_term_in_text
            _before_excl = len(new_articles)
            new_articles = [
                a for a in new_articles
                if not any(
                    _rss_term_in_text(kw, f"{a.get('title', '')} {a.get('content', '')}".lower())
                    for kw in _exclusion_kws
                )
            ]
            if len(new_articles) < _before_excl:
                _flog(f"[EXCL] 排除關鍵字過濾：{_before_excl} → {len(new_articles)} 篇")

        if not new_articles:
            _flog(f"[SCAN] No new articles found (force={force}), exiting")
            logger.info("Radar scan: no new articles found")
            return

        # 2.5 財經相關性篩選（可選，預設關閉）
        if _fin_filter_enabled:
            from backend.services.finance_filter import compute_finance_relevance
            _before_filter = len(new_articles)
            filtered = []
            for _a in new_articles:
                _score = compute_finance_relevance(
                    _a.get("title", ""), _a.get("content", "")
                )
                _a["finance_relevance"] = _score
                # 全文讀取來源：跳過篩選（已選擇信任該來源所有文章），但分數仍保留
                if _a.get("fetch_all_source"):
                    filtered.append(_a)
                elif _score >= _fin_threshold:
                    filtered.append(_a)
                else:
                    _flog(f"[FILTER] 排除低相關文章 ({_score:.2f}): {_a.get('title','')[:60]}")
            new_articles = filtered
            _flog(f"[FILTER] 財經篩選：{_before_filter} → {len(new_articles)} 篇（閾值 {_fin_threshold}）")
            if not new_articles:
                _flog("[FILTER] 所有文章被篩除，退出掃描")
                return
        else:
            # 篩選關閉時仍計算相關性分數（供四維評分使用），但不過濾
            from backend.services.finance_filter import compute_finance_relevance
            for _a in new_articles:
                if "finance_relevance" not in _a:
                    _a["finance_relevance"] = compute_finance_relevance(
                        _a.get("title", ""), _a.get("content", "")
                    )

        # 3. Save new articles to Article DB（用 SAVEPOINT 逐筆寫入，遇重複跳過）
        _now_for_scores = datetime.utcnow()
        for data in new_articles:
            try:
                _scores = _compute_article_scores(data, seen_content_fps, _now_for_scores)
                with db.begin_nested():
                    db.add(Article(
                        title=data.get("title", "").strip(),
                        content=data.get("content", ""),
                        source=data.get("source", ""),
                        source_url=data.get("source_url", ""),
                        published_at=_parse_datetime(data.get("published_at")),
                        category=data.get("category", "radar"),
                        composite_score=_scores["composite"],
                        finance_relevance=_scores["finance_relevance"],
                        novelty_score=_scores["novelty"],
                        decay_factor=_scores["decay"],
                        intensity_score=_scores["intensity"],
                        severity=_article_severity(data),
                    ))
            except IntegrityError:
                pass  # 已存在，略過

        # Save TopicArticle records collected above（同樣逐筆寫入）
        for topic_id, a in topic_articles_to_save:
            try:
                with db.begin_nested():
                    db.add(TopicArticle(
                        topic_id=topic_id,
                        title=a.get("title", "").strip(),
                        content=a.get("content", ""),
                        source=a.get("source", ""),
                        source_url=a.get("source_url", ""),
                        published_at=_parse_datetime(a.get("published_at")),
                        add_source="radar",
                    ))
            except IntegrityError:
                pass  # 已存在，略過
        db.commit()

        # 4. Match position exposure (from Google Sheets)
        positions = await get_positions()

        # 5. Group articles by topic → ONE alert per scan
        article_groups = _group_articles_by_topic(new_articles)
        logger.info(f"Radar scan: {len(new_articles)} articles → {len(article_groups)} topic groups → 1 alert")

        # Exposure matching across all articles
        matched = match_positions_to_news(positions, new_articles) if positions else []
        exposure_summary = format_exposure_summary(matched) if matched else ""

        # Build title
        first_title = new_articles[0].get("title", "").strip()
        if len(new_articles) == 1:
            alert_title = first_title
        elif len(article_groups) == 1:
            alert_title = f"[{len(new_articles)} 則相關] {first_title}"
        else:
            alert_title = f"[{len(article_groups)} 主題 / {len(new_articles)} 則] {first_title}"
        if force:
            alert_title = f"[手動] {alert_title}"

        # Dedup key: auto scans use hour precision (same story this hour = duplicate).
        # Force (manual) scans use minute precision so the user can re-trigger within the hour.
        now = datetime.utcnow()
        if force:
            time_str = now.strftime('%Y%m%d%H%M')
            dedup_key = f"scan:manual:{time_str}:{hashlib.md5(first_title.encode()).hexdigest()[:16]}"
        else:
            hour_str = now.strftime('%Y%m%d%H')
            dedup_key = f"scan:{hour_str}:{hashlib.md5(first_title.encode()).hexdigest()[:16]}"

        # 預先建立 article line formatter 與 source_urls（供去重合併與建立告警共用）
        def _fmt_article_line(a: dict) -> str:
            sev = _article_severity(a)
            kw = a.get('matched_keyword', '')
            base = f"[{a.get('source', '')}] {a.get('title', '')}"
            line = f"{base} (關鍵字：{kw})" if kw else base
            return f"{{{sev}}}{line}"

        # Store source_urls with severity prefix so frontend can filter them
        source_urls = [
            f"{{{_article_severity(a)}}}{a.get('source_url', '')}"
            for a in new_articles if a.get("source_url")
        ]

        # Prevent duplicate alerts: query by dedup_key
        recent_dupe = db.query(Alert).filter(Alert.dedup_key == dedup_key).first()
        if recent_dupe:
            _flog(f"[SCAN] Dedup hit: {dedup_key} → existing alert id={recent_dupe.id}")
            logger.warning(f"Duplicate alert prevented (same story this hour): {first_title}")
            return 0

        _flog(f"[SCAN] Creating alert: {len(new_articles)} articles, sev will be computed")

        alert = Alert(
            type="news",
            title=alert_title,
            content="\n".join(_fmt_article_line(a) for a in new_articles),
            analysis=None,
            severity=(max((_article_severity(a) for a in new_articles), key=lambda s: _SEVERITY_ORDER.get(s, 0)) if new_articles else "low"),
            source="Radar Scan",
            exposure_summary=exposure_summary or None,
            source_urls=json.dumps(source_urls) if source_urls else None,
            dedup_key=dedup_key,
        )
        db.add(alert)
        try:
            db.flush()
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.warning(f"Duplicate alert prevented (DB constraint): {alert_title}")
            return 0

        # 6. Broadcast + notify
        # 先收集 alert 資料（避免之後 session 問題）
        alert_data = {
            "title": alert.title,
            "content": alert.content,
            "analysis": alert.analysis,
            "severity": alert.severity,
            "source": alert.source,
            "source_url": getattr(alert, "source_url", None),
            "type": alert.type,
            "exposure_summary": exposure_summary,
            "source_urls": source_urls[:5],
        }
        alert_id = alert.id
        alert_sev = alert.severity

        _flog(f"[SCAN] Alert created id={alert_id} sev={alert_sev} title={alert_title[:50]}")

        # WebSocket broadcast（不影響通知）
        try:
            if _ws_manager:
                await _ws_manager.broadcast({
                    "type": "radar_alert",
                    "data": {
                        "id": alert_id,
                        "title": alert_data["title"],
                        "severity": alert_sev,
                        "content": (alert_data["content"] or "")[:300],
                        "exposure_summary": exposure_summary,
                        "source_urls": source_urls[:5],
                        "created_at": datetime.utcnow().isoformat(),
                    },
                })
                _flog("[SCAN] WS broadcast OK")
        except Exception as ws_err:
            _flog(f"[SCAN] WS broadcast ERROR: {ws_err}")

        # 通知派送（使用獨立 session，確保不受 scan session 狀態影響）
        try:
            _flog("[SCAN] Calling _send_notifications...")
            await _send_notifications_with_data(alert_data)
            _flog("[SCAN] Notifications OK")
        except Exception as notif_err:
            _flog(f"[SCAN] Notification ERROR: {notif_err}\n{traceback.format_exc()}")
            logger.error(f"Notification dispatch error: {notif_err}")

        # 自動將高/緊急文章寫入 Google Sheet（非阻塞，失敗不影響掃描）
        try:
            from backend.config import settings as _cfg
            if _cfg.GOOGLE_APPS_SCRIPT_URL:
                _urgent_rows = []
                for _a in new_articles:
                    _sev = _article_severity(_a)
                    if _sev in ("critical", "high"):
                        _urgent_rows.append({
                            "date":    datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                            "title":   _a.get("title", ""),
                            "keyword": _a.get("matched_keyword", ""),
                            "url":     _a.get("source_url", ""),
                        })
                if _urgent_rows:
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=10) as _c:
                        await _c.post(_cfg.GOOGLE_APPS_SCRIPT_URL,
                                      json={"articles": _urgent_rows},
                                      follow_redirects=True)
                    _flog(f"[SCAN] Wrote {len(_urgent_rows)} urgent articles to Google Sheet")
        except Exception as _gs_err:
            _flog(f"[SCAN] Google Sheet write failed (non-fatal): {_gs_err}")

        logger.info(f"Radar scan complete: {len(new_articles)} articles, {len(article_groups)} groups → 1 alert")
        return 1

    except Exception as e:
        _flog(f"[SCAN] EXCEPTION: {e}\n{traceback.format_exc()}")
        logger.error(f"Radar scan error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


async def market_check():
    """Check market indicators using signal conditions and trigger alerts on state changes."""
    from backend.services import market_data

    logger.info("Running market check...")
    db = SessionLocal()

    try:
        watchlist = db.query(MarketWatchItem).all()
        if not watchlist:
            return

        symbols = [w.symbol for w in watchlist]
        quotes = await market_data.get_market_quotes(symbols)
        quotes_map = {q["symbol"]: q for q in quotes}

        for item in watchlist:
            quote = quotes_map.get(item.symbol)
            if not quote or not quote.get("price"):
                continue

            price = quote["price"]
            change_pct = quote.get("change_percent", 0)

            # Update current value
            item.current_value = price
            item.change_percent = change_pct
            item.last_updated = datetime.utcnow()

            # Evaluate signal conditions (ordered by priority)
            conditions = (
                db.query(SignalCondition)
                .filter(SignalCondition.watchlist_id == item.id, SignalCondition.is_active == True)
                .order_by(SignalCondition.priority)
                .all()
            )

            new_signal = None
            triggered_cond = None

            for cond in conditions:
                if _evaluate_condition(cond, price):
                    new_signal = cond.signal
                    triggered_cond = cond
                    break  # first match by priority wins

            # Fallback: legacy threshold check if no conditions defined
            if not conditions:
                if item.threshold_upper and price >= item.threshold_upper:
                    new_signal = "negative"
                    triggered_cond = None
                elif item.threshold_lower and price <= item.threshold_lower:
                    new_signal = "negative"
                    triggered_cond = None

            # Only alert on signal state change
            old_signal = item.signal_status
            if new_signal and new_signal != old_signal:
                item.signal_status = new_signal

                trigger_msg = triggered_cond.message if triggered_cond else f"{item.name} 觸發閾值警報"
                severity = _signal_to_severity(new_signal, change_pct)

                # AI analysis is on-demand only (user triggers via UI)
                alert = Alert(
                    type="market",
                    title=f"📊 {item.name} — {trigger_msg}",
                    content=f"{item.name} ({item.symbol}) 當前值: {price} ({change_pct:+.2f}%)",
                    analysis=None,
                    severity=severity,
                    source="Market Monitor",
                )
                db.add(alert)

                if _ws_manager:
                    await _ws_manager.broadcast({
                        "type": "market_alert",
                        "data": {
                            "id": alert.id,
                            "title": alert.title,
                            "severity": alert.severity,
                            "symbol": item.symbol,
                            "price": price,
                            "change_percent": change_pct,
                            "signal_status": new_signal,
                            "analysis": None,
                        },
                    })

                await _send_notifications(alert)

            elif new_signal is None and old_signal is not None:
                # No condition matched — reset to neutral (no alert)
                item.signal_status = None

        db.commit()
        logger.info("Market check complete")
    except Exception as e:
        logger.error(f"Market check error: {e}")
        db.rollback()
    finally:
        db.close()


def _evaluate_condition(cond: SignalCondition, price: float) -> bool:
    """Evaluate a single signal condition against the current price."""
    op = cond.operator
    v = cond.value
    v2 = cond.value2

    if op == "gt":
        return price > v
    elif op == "lt":
        return price < v
    elif op == "gte":
        return price >= v
    elif op == "lte":
        return price <= v
    elif op == "between":
        return v is not None and v2 is not None and v <= price <= v2
    return False


def _signal_to_severity(signal: str, change_pct: float) -> str:
    """Map signal status + change magnitude to alert severity."""
    if signal == "negative":
        return "critical" if abs(change_pct) > 5 else "high"
    elif signal == "neutral":
        return "medium"
    return "low"


async def daily_news_fetch():
    """Daily job to collect news from all sources."""
    from backend.services import rss_feed
    from backend.services.google_news import search_google_news

    logger.info("Running daily news fetch...")
    db = SessionLocal()

    try:
        articles_data = []

        # Headlines from Google News RSS (multiple topics)
        for topic in ["金融市場", "台股", "美股", "經濟數據", "央行政策"]:
            results = await search_google_news(query=topic, hours_back=24, max_results=10)
            articles_data.extend(results)

        # RSS feeds
        sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "rss",
        ).all()
        feeds = [
            {
                "name": s.name,
                "url": s.url,
                "keywords": json.loads(s.keywords) if s.keywords else [],
                "fetch_all": bool(getattr(s, "fetch_all", False)),
            }
            for s in sources
        ]
        if feeds:
            rss_results = await rss_feed.fetch_multiple_feeds(feeds, hours_back=24)
            articles_data.extend(rss_results)

        # Save with dedup
        saved = 0
        seen_urls = set()
        seen_titles = set()
        for data in articles_data:
            url = data.get("source_url", "")
            title = data.get("title", "").strip()
            if not url or not title or url in seen_urls or title in seen_titles:
                continue
            if db.query(Article).filter(Article.source_url == url).first() or \
               db.query(Article).filter(Article.title == title).first():
                continue
            
            seen_urls.add(url)
            seen_titles.add(title)
            article = Article(
                title=data.get("title", ""),
                content=data.get("content", ""),
                source=data.get("source", ""),
                source_url=url,
                published_at=_parse_datetime(data.get("published_at")),
                category=data.get("category", "daily"),
            )
            db.add(article)
            saved += 1

        db.commit()
        logger.info(f"Daily news fetch complete: {saved} new articles saved")

        # Auto-append to Google Sheets via GAS
        if saved > 0:
            try:
                from backend.services.google_sheets import append_news_via_gas
                await append_news_via_gas(articles_data)
                logger.info(f"Appended {saved} articles to Google Sheets via GAS")
            except Exception as gs_err:
                logger.warning(f"Google Sheets GAS write failed: {gs_err}")

        # Broadcast summary
        if _ws_manager and saved > 0:
            await _ws_manager.broadcast({
                "type": "daily_summary",
                "data": {
                    "message": f"每日新聞蒐集完成：新增 {saved} 篇文章",
                    "count": saved,
                    "time": datetime.utcnow().isoformat(),
                },
            })

    except Exception as e:
        logger.error(f"Daily news fetch error: {e}")
        db.rollback()
    finally:
        db.close()


async def daily_research_fetch():
    """Daily job to collect research reports from IMF, BIS, Fed, ECB, BOJ, BOE."""
    from backend.services.research_feed import fetch_all_research_feeds

    logger.info("Running daily research fetch...")
    db = SessionLocal()

    try:
        sources = db.query(MonitorSource).filter(
            MonitorSource.type == "research",
            MonitorSource.is_active == True,
        ).all()

        if not sources:
            logger.info("No research sources configured")
            return

        feed_sources = [{"name": s.name, "url": s.url} for s in sources]
        reports_data = await fetch_all_research_feeds(feed_sources, hours_back=48)

        saved = 0
        for data in reports_data:
            url = data.get("source_url", "")
            if url and db.query(ResearchReport).filter(ResearchReport.source_url == url).first():
                continue
            report = ResearchReport(
                title=data.get("title", ""),
                abstract=data.get("abstract"),
                authors=data.get("authors"),
                source=data.get("source", ""),
                source_url=url,
                pdf_url=data.get("pdf_url") or url,
                publication_date=_parse_datetime(data.get("publication_date")),
            )
            db.add(report)
            saved += 1

        db.commit()
        logger.info(f"Daily research fetch complete: {saved} new reports saved")

        if _ws_manager and saved > 0:
            await _ws_manager.broadcast({
                "type": "research_summary",
                "data": {
                    "message": f"每日研究報告蒐集完成：新增 {saved} 篇報告",
                    "count": saved,
                    "time": datetime.utcnow().isoformat(),
                },
            })

    except Exception as e:
        logger.error(f"Daily research fetch error: {e}")
        db.rollback()
    finally:
        db.close()


async def youtube_check():
    """Check all active YouTube channels for new videos (runs every 30 min)."""
    from backend.database import YoutubeChannel, YoutubeVideo
    from backend.services.youtube_feed import fetch_channel_videos

    db = SessionLocal()
    try:
        channels = db.query(YoutubeChannel).filter(YoutubeChannel.is_active == True).all()
        if not channels:
            return

        total_new = 0
        for channel in channels:
            try:
                videos = await fetch_channel_videos(channel.channel_id)
                new_count = 0
                for v in videos:
                    if not db.query(YoutubeVideo).filter(YoutubeVideo.video_id == v["video_id"]).first():
                        db.add(YoutubeVideo(
                            channel_db_id=channel.id,
                            video_id=v["video_id"],
                            title=v["title"],
                            description=v["description"],
                            url=v["url"],
                            thumbnail_url=v["thumbnail_url"],
                            published_at=v["published_at"],
                            is_new=True,
                        ))
                        new_count += 1
                channel.last_checked_at = datetime.utcnow()
                total_new += new_count
                if new_count:
                    _flog(f"[YOUTUBE] {channel.name}: {new_count} new video(s)")
            except Exception as e:
                logger.error(f"YouTube check error for {channel.channel_id}: {e}")

        db.commit()
        if total_new > 0 and _ws_manager:
            await _ws_manager.broadcast({
                "type": "youtube_new_videos",
                "data": {
                    "count": total_new,
                    "message": f"YouTube 偵測到 {total_new} 支新影片",
                    "time": datetime.utcnow().isoformat(),
                },
            })
    except Exception as e:
        logger.error(f"YouTube check job error: {e}")
        db.rollback()
    finally:
        db.close()


async def _send_notifications(alert):
    """Send notifications through enabled channels (from Alert ORM object)."""
    alert_dict = {
        "title": alert.title,
        "content": alert.content,
        "analysis": alert.analysis,
        "severity": alert.severity,
        "source": alert.source,
        "source_url": getattr(alert, "source_url", None),
        "type": alert.type,
    }
    await _send_notifications_with_data(alert_dict)


async def _send_notifications_with_data(alert_dict: dict):
    """Send notifications through enabled channels.

    使用獨立 DB session，不依賴呼叫者的 session 狀態。
    所有例外皆被捕捉並記錄到檔案日誌，確保不會靜默失敗。
    """
    from backend.config import settings as _cfg
    from backend.services.notification import (
        format_alert_email,
        format_alert_message,
        send_discord_webhook,
        send_email,
        send_line_broadcast,
    )

    sev = alert_dict.get("severity", "low")
    _sev_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    # 使用獨立 session 查詢通知設定
    db = SessionLocal()
    try:
        settings_list = db.query(NotificationSetting).filter(
            NotificationSetting.is_enabled == True
        ).all()

        enabled_channels = [s.channel for s in settings_list]
        _flog(f"[NOTIF] 派送 sev={sev} title={alert_dict.get('title','')[:50]} channels={enabled_channels}")
        logger.info(f"通知派送 severity={sev} title={alert_dict.get('title','')[:40]} 已啟用={enabled_channels or '無'}")

        if not settings_list:
            _flog("[NOTIF] 無已啟用的通知頻道，跳過")
            return

        for setting in settings_list:
            try:
                if setting.channel == "line":
                    # 嚴格模式：只傳送含有 {critical} 文章的警報
                    content_lines = (alert_dict.get("content") or "").splitlines()
                    critical_lines = [l for l in content_lines if l.strip().startswith("{critical}")]
                    if not critical_lines:
                        _flog("[NOTIF] LINE SKIP: 無緊急文章")
                        continue
                    _flog(f"[NOTIF] LINE SENDING {len(critical_lines)} 則緊急文章")
                    msg = format_alert_message(alert_dict, min_severity="critical")
                    success = await send_line_broadcast(msg)
                    _flog(f"[NOTIF] LINE RESULT={'OK' if success else 'FAIL'}")
                    logger.info(f"LINE 傳送{'成功' if success else '失敗（請檢查 token 與 API 配額）'}")

                elif setting.channel == "discord":
                    try:
                        cfg_json = json.loads(setting.config) if setting.config else {}
                    except (json.JSONDecodeError, TypeError):
                        cfg_json = {}
                    webhook_url = cfg_json.get("webhook_url", "")
                    if webhook_url:
                        success = await send_discord_webhook(webhook_url, alert_dict)
                        _flog(f"[NOTIF] DISCORD RESULT={'OK' if success else 'FAIL'}")
                    else:
                        _flog("[NOTIF] DISCORD SKIP: webhook_url 未設定")

                elif setting.channel == "email":
                    try:
                        config = json.loads(setting.config) if setting.config else {}
                    except (json.JSONDecodeError, TypeError):
                        config = {}
                    recipient = config.get("recipient")
                    body = format_alert_email(alert_dict)
                    await send_email(
                        subject=f"[金融偵測] {alert_dict.get('title', '')}",
                        body=body,
                        recipient=recipient,
                    )
            except Exception as e:
                _flog(f"[NOTIF] ERROR channel={setting.channel}: {e}\n{traceback.format_exc()}")
                logger.error(f"Notification send error ({setting.channel}): {e}")
    except Exception as e:
        _flog(f"[NOTIF] FATAL: {e}\n{traceback.format_exc()}")
        logger.error(f"Notification dispatch fatal error: {e}")
    finally:
        db.close()


def _group_articles_by_topic(articles: list[dict]) -> list[list[dict]]:
    """Group articles by topic similarity using title keyword overlap.

    Articles sharing 2+ meaningful keywords are considered the same topic.
    Returns a list of groups (each group is a list of articles).
    """
    import re

    # Common stopwords to ignore (Chinese + English)
    stopwords = {
        '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '這', '中',
        '大', '上', '下', '為', '以', '而', '也', '但', '或', '於', '及', '與', '等', '已',
        'the', 'a', 'an', 'in', 'is', 'of', 'to', 'for', 'and', 'or', 'at', 'by',
    }

    def extract_keywords(title: str) -> set:
        keywords = set()
        # Uppercase abbreviations (ETF, FOMC, Fed…)
        for m in re.finditer(r'[A-Z]{2,}', title):
            keywords.add(m.group())
        # English words 4+ chars
        for m in re.finditer(r'[a-zA-Z]{4,}', title):
            keywords.add(m.group().lower())
        # CJK bigrams (sliding 2-char window) — better topic matching than max-match
        cjk = re.findall(r'[\u4e00-\u9fff]', title)
        for i in range(len(cjk) - 1):
            bigram = cjk[i] + cjk[i + 1]
            if bigram not in stopwords:
                keywords.add(bigram)
        return keywords

    keywords_list = [extract_keywords(a.get("title", "")) for a in articles]
    groups: list[list[dict]] = []
    used = set()

    for i, article in enumerate(articles):
        if i in used:
            continue
        group = [article]
        used.add(i)
        for j in range(i + 1, len(articles)):
            if j in used:
                continue
            # Same topic if titles share 2+ meaningful keywords
            if len(keywords_list[i] & keywords_list[j]) >= 2:
                group.append(articles[j])
                used.add(j)
        groups.append(group)

    return groups


_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_CRITICAL_KEYWORDS = [
    "崩盤", "暴跌", "危機", "crash", "crisis", "emergency",
    "戰爭", "制裁", "違約", "破產", "倒閉", "破產保護", "債務違約",
    "勒索軟體", "網路攻擊", "資料外洩",
]
_HIGH_KEYWORDS = [
    "升息", "降息", "衰退", "recession", "inflation", "通膨",
    "獨家", "重訊", "重大訊息", "盈餘警告", "虧損擴大", "淨損",
    "信用評等", "調降", "縮編", "重組", "裁員", "出口禁令",
]

# ── 多維風險評分 ───────────────────────────────────────────────────────────────

# 來源可信度權重（substring 比對，由長到短排列避免短串誤觸）
_SOURCE_WEIGHTS: dict = {
    "federalreserve": 1.6, "ecb.europa": 1.6, "bis.org": 1.5,
    "金管會": 1.6, "央行": 1.6, "mops": 1.5,
    "reuters": 1.5, "bloomberg": 1.5, "financial times": 1.5, "ft.com": 1.4,
    "wsj": 1.4, "economist": 1.4, "nikkei": 1.4,
    "cnbc": 1.2, "marketwatch": 1.2, "barron": 1.2, "fortune": 1.2,
    "yahoo finance": 1.1, "seekingalpha": 1.1,
    "經濟日報": 1.4, "工商時報": 1.4, "moneydj": 1.3, "鉅亨": 1.3,
    "聯合報": 1.2, "中時": 1.2, "自由時報": 1.2,
}

# 否定詞：出現在關鍵字前 6 字元內，視為語意否定
_NEGATION_WORDS = [
    "不會", "不至", "不太", "尚未", "避免", "防止", "排除",
    "不", "沒", "無", "非", "否", "未",
]

# 內容相似度去重用停用詞
_CONTENT_STOPWORDS = {
    "的", "了", "是", "在", "和", "與", "及", "有", "將", "為", "被", "對",
    "中", "以", "但", "而", "等", "這", "那", "也", "都", "就", "還",
    "a", "an", "the", "of", "in", "is", "to", "for", "on", "at", "be",
    "was", "were", "has", "have", "its", "by",
}


def _get_source_weight(source: str) -> float:
    """回傳來源可信度權重（預設 1.0）。"""
    s = source.lower().replace(" ", "")
    for key, w in _SOURCE_WEIGHTS.items():
        if key.replace(" ", "") in s:
            return w
    return 1.0


def _has_negation_before(text: str, keyword: str) -> bool:
    """檢查 keyword 在 text 中是否有否定詞前置（關鍵字前 6 字元內）。"""
    idx = 0
    while True:
        pos = text.find(keyword, idx)
        if pos < 0:
            break
        pre = text[max(0, pos - 6):pos]
        if any(neg in pre for neg in _NEGATION_WORDS):
            return True
        idx = pos + 1
    return False


def _compute_article_scores(article: dict, seen_fps: list, now: datetime) -> dict:
    """計算文章四維評分，完全本地運算，不呼叫任何 API。

    回傳 dict: composite, finance_relevance, novelty, decay, intensity
    """
    import math as _math
    from datetime import timezone as _tz

    # 1. 時間衰減：exp(-0.1 × hours_elapsed)
    hours = 0.0
    pub_str = article.get("published_at")
    if pub_str:
        try:
            pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub.tzinfo is not None:
                pub = pub.astimezone(_tz.utc).replace(tzinfo=None)
            hours = max(0.0, (now - pub).total_seconds() / 3600)
        except Exception:
            pass
    decay = _math.exp(-0.1 * hours)

    # 2. 新奇度：1/(1+similar_count)，利用現有 fingerprint 清單
    fp = _article_fingerprint(article.get("title", ""), article.get("content", ""))
    similar_count = 0
    for seen in seen_fps:
        if seen and len(fp | seen) > 0 and len(fp & seen) / len(fp | seen) >= 0.5:
            similar_count += 1
    novelty = 1.0 / (1 + similar_count)

    # 3. 財經相關性：若已在前一步驟計算過則直接取用
    finance_rel = float(article.get("finance_relevance") or 0.0)

    # 4. 情緒強度：複用 sentiment.py 詞彙表，不呼叫完整 analyze_sentiment()
    from backend.services.sentiment import POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS
    text_sample = (
        (article.get("title") or "") + " " + (article.get("content") or "")[:300]
    ).lower()
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_sample)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_sample)
    total_sig = pos + neg
    raw_sent = (pos - neg) / total_sig if total_sig > 0 else 0.0
    intensity = abs(raw_sent)

    # 5. 綜合分：decay × novelty × relevance × (0.5 + 0.5 × intensity)
    #    relevance 下限 0.05（避免 0 使整體為 0，但確保非財經文章得低分）
    composite = decay * novelty * max(finance_rel, 0.05) * (0.5 + 0.5 * intensity)

    return {
        "composite":        round(composite, 4),
        "finance_relevance": round(finance_rel, 4),
        "novelty":           round(novelty, 4),
        "decay":             round(decay, 4),
        "intensity":         round(intensity, 4),
    }


def _article_fingerprint(title: str, content: str) -> frozenset:
    """從標題+內文前 500 字抽取關鍵詞集合，供內容相似度比對。"""
    text = title + " " + content[:500]
    zh = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    en = [w.lower() for w in re.findall(r'[A-Za-z]{3,}', text)]
    return frozenset(set(zh + en) - _CONTENT_STOPWORDS)


def _is_content_duplicate(fp: frozenset, seen_fps: list, threshold: float = 0.65) -> bool:
    """若與任一已見 fingerprint 的 Jaccard 相似度 ≥ threshold，視為重複內容。
    [暫時停用] 內容指紋去重已全面關閉，函式直接回傳 False。"""
    return False  # 暫時停用：直接允許所有文章通過


def _apply_time_decay(severity: str, published_at_str: str | None, decay_hours: int = 6) -> str:
    """根據文章發布時間衰減嚴重度。
    超過 decay_hours 小時的文章降一級（critical→high, high→low）。
    """
    if not published_at_str or severity == "low":
        return severity
    try:
        pub = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
        # 統一轉為 naive UTC
        if pub.tzinfo is not None:
            from datetime import timezone
            pub = pub.astimezone(timezone.utc).replace(tzinfo=None)
        age_hours = (datetime.utcnow() - pub).total_seconds() / 3600
        if age_hours >= decay_hours:
            return "high" if severity == "critical" else "low"
    except Exception:
        pass
    return severity


def _assess_severity_single(article: dict, critical_kws=None, high_kws=None, rules=None, decay_hours: int = 6, known_sources: frozenset = frozenset()) -> str:
    """多維風險評分模型。

    評估順序：
    1. Boolean rules（使用者自訂，第一條符合即返回）
    2. 多維評分：
       a. 關鍵字命中（critical=3.0, high=2.0）
       b. 否定語氣過濾（「不會崩盤」不觸發 critical）
       c. × 來源可信度（Reuters/Bloomberg=1.5, 官方=1.6, 一般=1.0；
          GN 文章且來源不在 MonitorSource 清單中 → 0.65，更難觸發高/緊急）
       d. × 標題+內文同時命中確認（1.3x，僅標題或僅內文=1.0）
       e. × 多關鍵字加乘（每多一個命中 +0.1，上限 1.3）
       f. 映射：≥3.5→critical, ≥2.0→high, 否則→low
    3. 時間衰減（超過 decay_hours 降一級）
    """
    title = article.get("title", "")
    content_raw = article.get("content", "")[:300]
    matched_kw = (article.get("matched_keyword", "") or "")
    source = article.get("source", "")

    title_lower = title.lower()
    content_lower = content_raw.lower()
    full_text = title_lower + " " + content_lower + " " + matched_kw.lower()

    # 1. Boolean rules — 第一條符合即返回（不受多維評分影響）
    if rules:
        for rule in rules:
            cond = rule.get("condition", "")
            sev  = rule.get("severity", "low")
            if not cond:
                continue
            groups = _parse_keyword_groups(cond.split())
            if _match_keyword_groups(full_text, groups):
                return _apply_time_decay(sev, article.get("published_at"), decay_hours)

    # 2. 多維評分
    c = critical_kws if critical_kws is not None else _CRITICAL_KEYWORDS
    h = high_kws if high_kws is not None else _HIGH_KEYWORDS

    # 2a. 命中關鍵字（含否定過濾）
    crit_hits = [kw for kw in c if kw in full_text and not _has_negation_before(full_text, kw)]
    high_hits = [kw for kw in h if kw in full_text and not _has_negation_before(full_text, kw)]

    if not crit_hits and not high_hits:
        return _apply_time_decay("low", article.get("published_at"), decay_hours)

    # 2b. base score
    if crit_hits:
        base_score = 3.0
        ref_kws = crit_hits
    else:
        base_score = 2.0
        ref_kws = high_hits

    # 2c. 來源可信度
    source_w = _get_source_weight(source)
    # GN 文章且 _SOURCE_WEIGHTS 無明確權重 → 檢查是否為使用者設定來源；否則懲罰 0.65
    if source_w == 1.0 and known_sources and article.get("origin") == "gn":
        src_lower = source.lower()
        if not any(k in src_lower or src_lower in k for k in known_sources):
            source_w = 0.65

    # 2d. 標題+內文同時命中 → 1.3x
    in_title = any(kw in title_lower for kw in ref_kws)
    in_body  = any(kw in content_lower for kw in ref_kws)
    confirm_w = 1.3 if (in_title and in_body) else 1.0

    # 2e. 多關鍵字加乘（上限 1.3）
    kw_count = len(crit_hits) + len(high_hits)
    multi_w = min(1.0 + (kw_count - 1) * 0.1, 1.3)

    final_score = base_score * source_w * confirm_w * multi_w

    if final_score >= 3.5:
        base_sev = "critical"
    elif final_score >= 2.0:
        base_sev = "high"
    else:
        base_sev = "low"

    return _apply_time_decay(base_sev, article.get("published_at"), decay_hours)


def _extract_matched_terms(query, title: str, content: str = "") -> str:
    """Extract matched terms from a boolean query for display in the UI keyword badge.

    query 可以是 str 或 list[str]。
    - str：直接對該字串跑 _extract_display_kw（群組感知排序）
    - list：逐一尋找第一個「所有 AND-groups 都命中」的關鍵字，只對那個關鍵字萃取顯示詞。
      這樣可確保 badge 的第 1 個詞來自 Group A、第 2 個來自 Group B … 以此類推，
      不會因為 " ".join(kws) 把多個關鍵字合併後讓 _parse_topic_groups 誤判群組數量。
    """
    from backend.services.rss_feed import _extract_display_kw, _parse_topic_groups
    full_lower = title.lower() + " " + (content or "")[:400].lower()

    if isinstance(query, list):
        for kw in query:
            groups = _parse_topic_groups(kw)
            if all(any(term.lower() in full_lower for term in group) for group in groups):
                return _extract_display_kw(kw, full_lower)
        return ""

    return _extract_display_kw(query, full_lower)


def _assess_severity(articles: list[dict], critical_kws=None, high_kws=None, rules=None, decay_hours: int = 6, known_sources: frozenset = frozenset()) -> str:
    """Overall severity = max of all per-article severities."""
    if not articles:
        return "low"
    severities = [_assess_severity_single(a, critical_kws, high_kws, rules, decay_hours, known_sources) for a in articles]
    return max(severities, key=lambda s: _SEVERITY_ORDER.get(s, 0))




def _flatten_topics_to_keywords(topics: list[str]) -> list[str]:
    """Flatten radar topic strings (including boolean groups) into individual keyword terms.

    Used to build a global keyword fallback for RSS sources that have no source-specific keywords.
    Example:
      ["台股", '("Fed" OR "FOMC") 升息'] → ["台股", "Fed", "FOMC", "升息"]
    """
    import re as _re
    keywords: set[str] = set()
    for topic in topics:
        # Extract double-quoted terms
        for q in _re.findall(r'"([^"]+)"', topic):
            kw = q.strip()
            if kw:
                keywords.add(kw)
        # Strip quoted segments, parens, and OR/AND operators; keep remaining words
        remainder = _re.sub(r'"[^"]*"', '', topic)
        remainder = _re.sub(r'\b(?:OR|AND)\b', ' ', remainder, flags=_re.IGNORECASE)
        for word in _re.split(r'[\s()]+', remainder):
            word = word.strip()
            if word and len(word) > 1:
                keywords.add(word)
    return list(keywords)


def _parse_keyword_groups(keywords: list[str]) -> list[list[str]]:
    """Parse a keyword list into AND-groups of OR-terms.

    Supported formats (auto-detected):
      Grouped:  ["(Moody's OR 穆迪 OR Fitch)", "(降評 OR 負面展望)", "(台灣 OR 美國)"]
                or ['("Moody\\'s" OR "穆迪") ("降評") ("台灣")']
                → [[Moody's, 穆迪, Fitch], [降評, 負面展望], [台灣, 美國]]
                Matching: ALL groups must match (AND), each group = any term matches (OR)

      Simple:   ["Moody's", "穆迪", "降評"]
                → [[Moody's, 穆迪, 降評]]
                Matching: any term matches (OR)
    """
    import re
    full = " ".join(keywords)
    raw_groups = re.findall(r"\(([^)]+)\)", full)
    if raw_groups:
        groups = []
        for raw in raw_groups:
            terms = [t.strip().strip("\"'") for t in re.split(r"\bOR\b", raw, flags=re.IGNORECASE)]
            terms = [t for t in terms if t]
            if terms:
                groups.append(terms)
        return groups or [keywords]
    return [keywords]


def _match_keyword_groups(text: str, groups: list[list[str]]) -> bool:
    """Return True if text satisfies ALL groups (AND), each group via ANY term (OR)."""
    tl = text.lower()
    return all(any(term.lower() in tl for term in group) for group in groups)


_RADAR_MAX_QUERIES = 20     # cap per topic for radar scan
_RADAR_CONCURRENCY = 5      # max simultaneous Google News requests during radar scan


async def _multi_search_topic(
    keywords: list[str],
    hours_back: int = 1,
    max_per_query: int = 15,
) -> list[dict]:
    """Parallel multi-query search for radar scan.

    Simple keywords (no brackets): one query per keyword in parallel for full recall.
    2 groups, pairs ≤ RADAR_MAX_QUERIES → cross-product (parallel).
    Otherwise → anchor on smallest group (parallel, capped).
    Returns deduplicated articles.
    """
    import asyncio
    from backend.services.google_news import search_google_news

    groups = _parse_keyword_groups(keywords)
    if len(groups) <= 1:
        if len(keywords) <= 1:
            # Single keyword: direct query
            gn_query = _build_topic_gn_query(keywords)
            return await search_google_news(query=gn_query, hours_back=hours_back, max_results=max_per_query)
        # Multiple simple keywords → one query per keyword (parallel, capped)
        kw_queries = keywords[:_RADAR_MAX_QUERIES]
        semaphore = asyncio.Semaphore(_RADAR_CONCURRENCY)

        async def _fetch_simple(kw: str) -> list[dict]:
            async with semaphore:
                try:
                    return await search_google_news(query=kw, hours_back=hours_back, max_results=max_per_query)
                except Exception:
                    return []

        batch_results = await asyncio.gather(*[_fetch_simple(kw) for kw in kw_queries])
        seen_urls: set[str] = set()
        all_articles: list[dict] = []
        for batch in batch_results:
            for a in batch:
                url = a.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(a)
        return all_articles

    if len(groups) == 2:
        pairs = [(a, b) for a in groups[0] for b in groups[1]]
        if len(pairs) <= _RADAR_MAX_QUERIES:
            queries = [f'"{a}" "{b}"' for a, b in pairs]
        else:
            min_gi = 0 if len(groups[0]) <= len(groups[1]) else 1
            anchor = groups[min_gi][:_RADAR_MAX_QUERIES]
            rest = " OR ".join(f'"{t}"' for g in groups if g is not groups[min_gi] for t in g)
            queries = [f'"{t}" ({rest})' for t in anchor]
    else:
        min_gi = min(range(len(groups)), key=lambda i: len(groups[i]))
        anchor = groups[min_gi][:_RADAR_MAX_QUERIES]
        rest = " OR ".join(f'"{t}"' for i, g in enumerate(groups) if i != min_gi for t in g)
        queries = [f'"{t}" ({rest})' for t in anchor]

    semaphore = asyncio.Semaphore(_RADAR_CONCURRENCY)

    async def _fetch(q: str) -> list[dict]:
        async with semaphore:
            try:
                return await search_google_news(query=q, hours_back=hours_back, max_results=max_per_query)
            except Exception:
                return []

    batch_results = await asyncio.gather(*[_fetch(q) for q in queries])

    seen_urls: set[str] = set()
    all_articles: list[dict] = []
    for batch in batch_results:
        for a in batch:
            url = a.get("source_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_articles.append(a)
    return all_articles


def _build_topic_gn_query(keywords: list[str]) -> str:
    """Build a Google News RSS query string from topic keywords.

    If keywords contain parenthesized boolean syntax, pass through as-is.
    Otherwise join simple terms with OR.
    """
    import re
    full = " ".join(keywords)
    if re.search(r"\(", full):
        return full  # boolean expression — Google News understands it
    return " OR ".join(keywords)


def _parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse datetime string and normalize to naive UTC for consistent DB storage.

    RSS feeds may publish in various timezones (+08:00, +00:00 etc.).
    We convert all to naive UTC so the API can append "Z" and JavaScript
    displays times correctly in local timezone.
    """
    if not dt_str:
        return None
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, AttributeError):
        return None
