import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from backend.config import settings

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- Models ---

class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text)
    summary = Column(Text)
    source = Column(String)
    source_url = Column(String)
    category = Column(String)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    is_saved = Column(Boolean, default=False)
    user_notes = Column(Text)
    tags = Column(Text)  # JSON array string
    # 四維評分（掃描時本地計算，無 API 呼叫）
    composite_score   = Column(Float, nullable=True)  # 綜合分 0.0~1.0
    finance_relevance = Column(Float, nullable=True)  # 財經相關性（TF-IDF 近似）
    novelty_score     = Column(Float, nullable=True)  # 新奇度 1/(1+similar_count)
    decay_factor      = Column(Float, nullable=True)  # 時間衰減 exp(-0.1×hours)
    intensity_score   = Column(Float, nullable=True)  # 情緒強度 abs(sentiment)
    matched_keyword   = Column(String, nullable=True)  # 符合的關鍵字（儲存時帶入）
    severity          = Column(String, nullable=True)  # 掃描時評估的文章風險等級（含 fixed_severity）


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String)  # 'news' | 'market' | 'social'
    title = Column(String)
    content = Column(Text)
    analysis = Column(Text)
    severity = Column(String)  # 'low' | 'medium' | 'high' | 'critical'
    source = Column(String)
    source_url = Column(String)
    exposure_summary = Column(Text)
    source_urls = Column(Text)  # JSON array string
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)
    is_saved = Column(Boolean, default=False)
    # Dedup key: prevents DB-level duplicates across concurrent processes (e.g. --reload race)
    # Format for radar alerts: "scan:{YYYYMMDDHH}:{md5(title)[:16]}"
    # Format for legacy/other rows: "legacy:{id}"
    dedup_key = Column(String, nullable=True, unique=True)


class MarketWatchItem(Base):
    __tablename__ = "market_watchlist"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    name = Column(String)
    current_value = Column(Float)
    change_percent = Column(Float)
    threshold_upper = Column(Float)
    threshold_lower = Column(Float)
    last_updated = Column(DateTime)
    category = Column(String)  # 'equity' | 'bond' | 'currency' | 'commodity' | 'crypto' | 'volatility'
    description = Column(String)
    signal_status = Column(String)  # 'positive' | 'neutral' | 'negative'
    sort_order = Column(Integer, default=0)

    conditions = relationship("SignalCondition", back_populates="watchlist_item", cascade="all, delete-orphan")


class SignalCondition(Base):
    __tablename__ = "signal_conditions"

    id = Column(Integer, primary_key=True, index=True)
    watchlist_id = Column(Integer, ForeignKey("market_watchlist.id"), nullable=False)
    name = Column(String)
    operator = Column(String)  # 'gt' | 'lt' | 'gte' | 'lte' | 'between' | 'cross_above' | 'cross_below'
    value = Column(Float)
    value2 = Column(Float)  # second value for 'between'
    signal = Column(String)  # 'positive' | 'neutral' | 'negative'
    message = Column(String)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # higher priority evaluated first

    watchlist_item = relationship("MarketWatchItem", back_populates="conditions")


class MonitorSource(Base):
    __tablename__ = "monitor_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    type = Column(String)  # 'rss' | 'website' | 'social' | 'newsapi'
    url = Column(String)
    keywords = Column(Text)  # JSON array
    is_active = Column(Boolean, default=True)
    fetch_all = Column(Boolean, default=False)  # 全文讀取：跳過關鍵字過濾，但仍標記匹配關鍵字
    sort_order = Column(Integer, default=0)     # 使用者自訂排序（越小越前）
    fixed_severity = Column(String, nullable=True)  # None=動態評估 | 'critical'|'high'|'low'=強制覆寫
    is_deleted = Column(Boolean, default=False)  # 軟刪除：使用者刪除後設為 True，migration 不重新插入
    last_attempt_at = Column(DateTime, nullable=True)   # 最後一次嘗試抓取時間（成功或失敗）
    last_success_at = Column(DateTime, nullable=True)   # 最後一次 HTTP 200 成功時間
    last_error = Column(String(500), nullable=True)     # 最後一次失敗的錯誤訊息（成功時清空）


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String)  # 'web' | 'line' | 'email'
    is_enabled = Column(Boolean, default=True)
    config = Column(Text)  # JSON


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    keywords = Column(Text)  # JSON array of strings
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    articles = relationship("TopicArticle", back_populates="topic", cascade="all, delete-orphan")


class TopicArticle(Base):
    __tablename__ = "topic_articles"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    title = Column(String)
    content = Column(Text)
    source = Column(String)
    source_url = Column(String)
    published_at = Column(DateTime)
    added_at = Column(DateTime, default=datetime.utcnow)
    add_source = Column(String, default="radar")  # 'radar' | 'manual'

    topic = relationship("Topic", back_populates="articles")


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    abstract = Column(Text)           # 摘要
    authors = Column(Text)            # JSON array 字串
    source = Column(String)           # 機構名稱：IMF、BIS、Fed…
    source_url = Column(String)       # 報告頁面連結
    pdf_url = Column(String)          # PDF 下載連結
    publication_date = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    is_saved = Column(Boolean, default=False)
    tags = Column(Text)               # JSON array
    user_notes = Column(Text)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String, primary_key=True)
    value = Column(Text)


class YoutubeChannel(Base):
    __tablename__ = "youtube_channels"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(String, unique=True, nullable=False)  # UCxxxxxxxxx
    name = Column(String)
    url = Column(String)           # user-provided original input
    thumbnail_url = Column(String)
    is_active = Column(Boolean, default=True)
    check_interval_minutes = Column(Integer, default=30)
    last_checked_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    videos = relationship("YoutubeVideo", back_populates="channel", cascade="all, delete-orphan")


class YoutubeVideo(Base):
    __tablename__ = "youtube_videos"

    id = Column(Integer, primary_key=True, index=True)
    channel_db_id = Column(Integer, ForeignKey("youtube_channels.id"), nullable=False)
    video_id = Column(String, unique=True, nullable=False)   # YouTube video ID
    title = Column(String)
    description = Column(Text)
    url = Column(String)
    thumbnail_url = Column(String)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    is_new = Column(Boolean, default=True)   # True until user marks as seen

    channel = relationship("YoutubeChannel", back_populates="videos")


class NlmReport(Base):
    """累積保存每次 NotebookLM 生成的分析報告（不覆蓋）。"""
    __tablename__ = "nlm_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_type = Column(String, default="news")   # "news" | "yt"
    content = Column(Text)
    generated_at = Column(DateTime, default=datetime.utcnow)
    source_title = Column(String)


class Feedback(Base):
    """使用者意見回饋。"""
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, default="general")  # general | bug | feature | ui
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Database Helpers ---

def init_db():
    """Create all tables and seed default data."""
    Base.metadata.create_all(bind=engine)
    _migrate_db()
    _seed_defaults()


def _backfill_alert_content_severity():
    """Add {severity} prefix to content lines that lack it (old alerts created before the prefix was added).

    Idempotent — skips alerts where all non-empty lines already have a prefix.
    """
    import re as _re
    import sqlite3 as _sq3

    _CRITICAL = [
        "崩盤", "暴跌", "危機", "crash", "crisis", "emergency",
        "戰爭", "制裁", "違約", "破產", "倒閉", "債務違約", "勒索軟體", "網路攻擊", "資料外洩",
    ]
    _HIGH = [
        "升息", "降息", "衰退", "recession", "inflation", "通膨",
        "獨家", "重訊", "重大訊息", "盈餘警告", "虧損擴大", "淨損",
        "信用評等", "調降", "縮編", "重組", "裁員", "出口禁令",
    ]

    def _line_sev(text: str) -> str:
        t = text.lower()
        if any(kw in t for kw in _CRITICAL):
            return "critical"
        if any(kw in t for kw in _HIGH):
            return "high"
        return "low"

    prefix_re = _re.compile(r"^\{(critical|high|medium|low)\}")
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = _sq3.connect(db_path)
        rows = conn.execute("SELECT id, content FROM alerts WHERE content IS NOT NULL").fetchall()
        updated = 0
        for alert_id, content in rows:
            lines = content.split("\n")
            if all(not line.strip() or prefix_re.match(line) for line in lines):
                continue  # all non-empty lines already prefixed
            new_lines = []
            changed = False
            for line in lines:
                if line.strip() and not prefix_re.match(line):
                    new_lines.append(f"{{{_line_sev(line)}}}{line}")
                    changed = True
                else:
                    new_lines.append(line)
            if changed:
                conn.execute("UPDATE alerts SET content=? WHERE id=?", ("\n".join(new_lines), alert_id))
                updated += 1
        conn.commit()
        conn.close()
        if updated:
            import logging
            logging.getLogger(__name__).info(f"Migration: backfilled content severity prefix on {updated} alerts")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Content severity backfill skipped: {e}")


def _backfill_alert_source_url_severity():
    """One-time backfill: add {severity} prefix to source_urls that lack it.

    Runs idempotently — skips alerts where all source_urls already have a prefix.
    Uses raw sqlite3 to avoid SQLAlchemy transaction complexity.
    """
    import json as _json
    import re as _re
    import sqlite3 as _sq3

    prefix_re = _re.compile(r"^\{(critical|high|medium|low)\}")
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = _sq3.connect(db_path)
        rows = conn.execute(
            "SELECT id, content, source_urls, severity FROM alerts WHERE source_urls IS NOT NULL"
        ).fetchall()
        updated = 0
        for alert_id, content, raw_urls, alert_sev in rows:
            try:
                urls = _json.loads(raw_urls)
            except Exception:
                continue
            if not urls or all(prefix_re.match(u) for u in urls):
                continue
            lines = (content or "").split("\n")
            line_sevs = []
            for line in lines:
                m = _re.match(r"^\{(critical|high|medium|low)\}", line)
                line_sevs.append(m.group(1) if m else "low")
            fallback = alert_sev or "low"
            new_urls = []
            for i, u in enumerate(urls):
                if prefix_re.match(u):
                    new_urls.append(u)
                else:
                    sev = line_sevs[i] if i < len(line_sevs) else fallback
                    new_urls.append(f"{{{sev}}}{u}")
            conn.execute("UPDATE alerts SET source_urls=? WHERE id=?",
                         (_json.dumps(new_urls), alert_id))
            updated += 1
        conn.commit()
        conn.close()
        if updated:
            import logging
            logging.getLogger(__name__).info(f"Migration: backfilled severity prefix on {updated} alerts")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Migration backfill skipped: {e}")


def _migrate_db():
    """Apply incremental schema migrations for SQLite (ALTER TABLE ADD COLUMN)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        # Add is_saved to alerts if missing
        try:
            conn.execute(text("ALTER TABLE alerts ADD COLUMN is_saved BOOLEAN DEFAULT 0"))
            conn.commit()
        except Exception:
            pass  # Column already exists

        # Add dedup_key column for cross-process duplicate prevention
        try:
            conn.execute(text("ALTER TABLE alerts ADD COLUMN dedup_key TEXT"))
            conn.commit()
        except Exception:
            pass  # Column already exists
        # Backfill old rows so they don't occupy NULL (NULL is not unique in SQLite)
        conn.execute(text(
            "UPDATE alerts SET dedup_key = 'legacy:' || CAST(id AS TEXT) WHERE dedup_key IS NULL"
        ))
        conn.commit()
        # Create unique index (idempotent)
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_alerts_dedup_key ON alerts(dedup_key)"
        ))
        conn.commit()

        # Backfill severity prefix on alert content lines and source_urls
        _backfill_alert_content_severity()
        _backfill_alert_source_url_severity()

        # Create topics and topic_articles tables
        conn.execute(text("""CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            keywords TEXT, is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS topic_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
            title TEXT, content TEXT, source TEXT, source_url TEXT,
            published_at DATETIME, added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            add_source TEXT DEFAULT 'radar')"""))
        conn.commit()

        # 清除 topic_articles 重複資料（相同 topic_id + source_url，保留 id 最小者）
        conn.execute(text("""
            DELETE FROM topic_articles
            WHERE source_url IS NOT NULL AND source_url != ''
              AND id NOT IN (
                SELECT MIN(id) FROM topic_articles
                WHERE source_url IS NOT NULL AND source_url != ''
                GROUP BY topic_id, source_url
              )
        """))
        conn.commit()
        # 部分唯一索引（排除 NULL / 空字串），防止未來重複
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_topic_articles_topic_url "
            "ON topic_articles(topic_id, source_url) "
            "WHERE source_url IS NOT NULL AND source_url != ''"
        ))
        conn.commit()

        # 清除 articles 重複資料（相同 source_url，保留 id 最小者）
        conn.execute(text("""
            DELETE FROM articles
            WHERE source_url IS NOT NULL AND source_url != ''
              AND id NOT IN (
                SELECT MIN(id) FROM articles
                WHERE source_url IS NOT NULL AND source_url != ''
                GROUP BY source_url
              )
        """))
        conn.commit()
        # 部分唯一索引
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_articles_source_url "
            "ON articles(source_url) "
            "WHERE source_url IS NOT NULL AND source_url != ''"
        ))
        conn.commit()

        # Create research_reports table
        conn.execute(text("""CREATE TABLE IF NOT EXISTS research_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            abstract TEXT,
            authors TEXT,
            source TEXT,
            source_url TEXT,
            pdf_url TEXT,
            publication_date DATETIME,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_saved BOOLEAN DEFAULT 0,
            tags TEXT,
            user_notes TEXT)"""))
        conn.commit()

        # Add new research sources (idempotent by name)
        new_research = [
            # IMF
            ("IMF World Economic Outlook", "https://www.imf.org/en/Publications/WEO/Issues/RSS",
             '["IMF","WEO","global growth","GDP","economic outlook"]'),
            ("IMF Global Financial Stability Report", "https://www.imf.org/en/Publications/GFSR/Issues/RSS",
             '["IMF","GFSR","financial stability","systemic risk","credit"]'),
            ("IMF Fiscal Monitor", "https://www.imf.org/en/Publications/FM/Issues/RSS",
             '["IMF","fiscal","debt","deficit","government spending"]'),
            ("IMF Staff Country Reports", "https://www.imf.org/en/Publications/CR/Issues/RSS",
             '["IMF","country report","Article IV","economy","outlook"]'),
            # BIS
            ("BIS Quarterly Review", "https://www.bis.org/doclist/qtrrev.rss",
             '["BIS","quarterly review","global finance","banking","market"]'),
            ("BIS Papers", "https://www.bis.org/doclist/bispap.rss",
             '["BIS","central bank","policy","financial system"]'),
            # Fed
            ("Fed Working Papers (FEDS)", "https://www.federalreserve.gov/feeds/working_papers.xml",
             '["Fed","FEDS","monetary policy","macroeconomics","finance"]'),
            ("NY Fed Staff Reports", "https://www.newyorkfed.org/research/staff_reports/rss.xml",
             '["NY Fed","staff report","monetary policy","markets","macroeconomics"]'),
            ("SF Fed Economic Letters", "https://www.frbsf.org/economic-research/feeds/el/",
             '["SF Fed","economic letter","monetary policy","labor","inflation"]'),
            # ECB
            ("ECB Occasional Papers", "https://www.ecb.europa.eu/rss/oppubs.rss",
             '["ECB","occasional paper","euro","monetary policy","financial"]'),
            ("ECB Economic Bulletin", "https://www.ecb.europa.eu/rss/ecbbulletin.rss",
             '["ECB","economic bulletin","euro area","inflation","growth"]'),
            # BOE
            ("BOE Quarterly Bulletin", "https://www.bankofengland.co.uk/rss/publications?PublicationTypes=2",
             '["BOE","quarterly bulletin","UK economy","monetary policy"]'),
            # NBER
            ("NBER Working Papers", "https://www.nber.org/rss/new_releases_rss.xml",
             '["NBER","working paper","economics","finance","research"]'),
            # BOK
            ("BOK Research", "https://www.bok.or.kr/eng/bbs/E0000634/list.do?menuNo=400069&rss=yes",
             '["BOK","Korea","monetary policy","won","interest rate"]'),
        ]
        for name, url, kw in new_research:
            exists = conn.execute(
                text("SELECT id FROM monitor_sources WHERE url = :u LIMIT 1"),
                {"u": url}
            ).fetchone()
            if not exists:
                conn.execute(text(
                    "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                    "VALUES (:n, 'research', :u, :k, 1)"
                ), {"n": name, "u": url, "k": kw})
        conn.commit()

        # Fix broken research sources (IMF/ECB RSS returns HTML; BIS QR/Papers are 404)
        # IMF: deactivate — their RSS is JavaScript-rendered, not parseable
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE name IN ('IMF Working Papers','IMF Publications','IMF World Economic Outlook',"
            "'IMF Global Financial Stability Report','IMF Fiscal Monitor','IMF Staff Country Reports') "
            "AND type='research'"
        ))
        # BIS: keep Working Papers only; deactivate QR and Papers (404)
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE name IN ('BIS Quarterly Review','BIS Papers') AND type='research'"
        ))
        # ECB: all ECB RSS feeds return 404; deactivate
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE name IN ('ECB Working Papers','ECB Financial Stability Review',"
            "'ECB Occasional Papers','ECB Economic Bulletin') AND type='research'"
        ))
        # BOK Research: RSS returns 0 entries; deactivate
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE name='BOK Research' AND type='research'"
        ))
        # NBER: blocks bots (403); deactivate
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE name='NBER Working Papers' AND type='research'"
        ))

        # Fix Fed: use actual working papers feed instead of press releases
        conn.execute(text(
            "UPDATE monitor_sources SET name='Fed Working Papers (FEDS)', "
            "url='https://www.federalreserve.gov/feeds/feds.xml', "
            "keywords='[\"Fed\",\"monetary policy\",\"inflation\",\"interest rate\",\"financial stability\"]', "
            "is_active=1 "
            "WHERE name IN ('Fed FEDS Notes','Fed Financial Stability Report') AND type='research'"
        ))
        # Fix BOE: remove broken PublicationTypes filter
        conn.execute(text(
            "UPDATE monitor_sources SET name='BOE Publications', "
            "url='https://www.bankofengland.co.uk/rss/publications', "
            "keywords='[\"BOE\",\"financial stability\",\"monetary policy\",\"UK\",\"interest rate\"]', "
            "is_active=1 "
            "WHERE name IN ('BOE Staff WP','BOE Financial Stability Report') AND type='research'"
        ))
        # Fix BOJ: keep existing URL, update name
        conn.execute(text(
            "UPDATE monitor_sources SET name='BOJ Research & Publications', "
            "keywords='[\"BOJ\",\"Bank of Japan\",\"monetary policy\",\"yen\",\"financial system\"]', "
            "is_active=1 "
            "WHERE name IN ('BOJ Research','BOJ Financial System Report') AND type='research'"
        ))
        # Deactivate other non-working feeds
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE name IN ('Fed Working Papers (FEDS) old','NY Fed Staff Reports',"
            "'SF Fed Economic Letters','BOE Quarterly Bulletin') AND type='research'"
        ))
        # Add Fed IFDP if not already present
        ifdp_exists = conn.execute(
            text("SELECT id FROM monitor_sources WHERE name='Fed IFDP Papers' AND type='research'")
        ).fetchone()
        if not ifdp_exists:
            conn.execute(text(
                "INSERT INTO monitor_sources (name, type, url, keywords, is_active) VALUES "
                "('Fed IFDP Papers', 'research', 'https://www.federalreserve.gov/feeds/ifdp.xml', "
                "'[\"Fed\",\"international finance\",\"exchange rate\",\"global economy\",\"trade\"]', 1)"
            ))
        conn.commit()

        # Re-enable IMF/ECB/NBER via RePEc/IDEAS HTML scraping (RSS broken, HTML works)
        conn.execute(text(
            "UPDATE monitor_sources SET name='IMF Working Papers', "
            "url='https://ideas.repec.org/s/imf/imfwpa.html', "
            "keywords='[\"IMF\",\"monetary\",\"fiscal\",\"global economy\",\"debt\",\"growth\"]', "
            "is_active=1 "
            "WHERE name IN ('IMF Working Papers','IMF Publications') AND type='research'"
        ))
        conn.execute(text(
            "UPDATE monitor_sources SET name='ECB Working Papers', "
            "url='https://ideas.repec.org/s/ecb/ecbwps.html', "
            "keywords='[\"ECB\",\"monetary policy\",\"euro\",\"inflation\",\"financial stability\"]', "
            "is_active=1 "
            "WHERE name IN ('ECB Working Papers','ECB Financial Stability Review') AND type='research'"
        ))
        conn.execute(text(
            "UPDATE monitor_sources SET name='NBER Working Papers', "
            "url='https://ideas.repec.org/s/nbr/nberwo.html', "
            "keywords='[\"NBER\",\"economics\",\"finance\",\"monetary\",\"labor\",\"trade\"]', "
            "is_active=1 "
            "WHERE name='NBER Working Papers' AND type='research'"
        ))
        conn.commit()

        # Create system_config table and seed defaults
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)"
        ))
        conn.commit()
        for key, default in [
            ("radar_topics", '["金融", "股市", "經濟"]'),
            ("radar_hours_back", "24"),
            ("gn_critical_only", "true"),
            ("finance_filter_enabled", "true"),
            ("finance_relevance_threshold", "0.15"),
        ]:
            if not conn.execute(text("SELECT value FROM system_config WHERE key = :k"), {"k": key}).fetchone():
                conn.execute(text("INSERT INTO system_config (key, value) VALUES (:k, :v)"), {"k": key, "v": default})
        conn.commit()

        # YouTube channel monitoring tables
        conn.execute(text("""CREATE TABLE IF NOT EXISTS youtube_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE NOT NULL,
            name TEXT,
            url TEXT,
            thumbnail_url TEXT,
            is_active BOOLEAN DEFAULT 1,
            check_interval_minutes INTEGER DEFAULT 30,
            last_checked_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS youtube_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_db_id INTEGER REFERENCES youtube_channels(id) ON DELETE CASCADE,
            video_id TEXT UNIQUE NOT NULL,
            title TEXT,
            description TEXT,
            url TEXT,
            thumbnail_url TEXT,
            published_at DATETIME,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_new BOOLEAN DEFAULT 1)"""))
        conn.commit()

        # 新增 MOPS 公開資訊觀測站來源（type="mops"，idempotent）
        mops_exists = conn.execute(
            text("SELECT id FROM monitor_sources WHERE type = 'mops' LIMIT 1")
        ).fetchone()
        if not mops_exists:
            conn.execute(text(
                "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                "VALUES ('公開資訊觀測站重大訊息', 'mops', 'https://mops.twse.com.tw/mops/web/t05sr01', "
                "'[\"重大訊息\",\"重訊\",\"法說\",\"盈餘\"]', 1)"
            ))
        conn.commit()

        # 修正金管會 RSS URL（原來是 HTML 頁面非 RSS）
        conn.execute(text(
            "UPDATE monitor_sources SET "
            "url='https://www.fsc.gov.tw/rss/rss_news.xml', "
            "name='金管會新聞稿 (FSC)' "
            "WHERE name IN ('台灣金管會','金管會新聞稿 (FSC)') AND type='rss' "
            "AND url LIKE '%fsc.gov.tw%'"
        ))
        conn.commit()

        # 修正常見台灣媒體來源的錯誤 RSS URL（依名稱比對，idempotent）
        # 使用者常把網站首頁 URL 填入，這裡自動更正為正確的 RSS Feed URL
        _rss_url_fixes = [
            ("鏡新聞",   "https://www.mirrormedia.mg/rss/rss.xml"),
            ("Mirror Media", "https://www.mirrormedia.mg/rss/rss.xml"),
            ("財訊",     "https://www.wealth.com.tw/rss"),
            ("WEALTH",   "https://www.wealth.com.tw/rss"),
            ("商周",     "http://cmsapi.businessweekly.com.tw/?CategoryId=24612ec9-2ac5-4e1f-ab04-310879f89b33&TemplateId=8E19CF43-50E5-4093-B72D-70A912962D55"),
            ("Business Weekly", "http://cmsapi.businessweekly.com.tw/?CategoryId=24612ec9-2ac5-4e1f-ab04-310879f89b33&TemplateId=8E19CF43-50E5-4093-B72D-70A912962D55"),
            ("經濟學人", "https://www.economist.com/finance-and-economics/rss.xml"),
            ("The Economist", "https://www.economist.com/finance-and-economics/rss.xml"),
            ("politico", "https://rss.politico.com/morningmoney.xml"),
            ("Politico",  "https://rss.politico.com/morningmoney.xml"),
            ("自由時報", "https://news.ltn.com.tw/rss/business.xml"),
        ]
        for src_name, correct_url in _rss_url_fixes:
            # 只更新：名稱包含關鍵字 且 type=rss 且 URL 不是正確的 RSS URL
            conn.execute(text(
                "UPDATE monitor_sources SET url = :u "
                "WHERE type = 'rss' AND name LIKE :n AND url != :u "
                "AND url NOT LIKE '%.xml' AND url NOT LIKE '%.aspx' "
                "AND url NOT LIKE '%/rss%' AND url NOT LIKE '%/feed%'"
            ), {"u": correct_url, "n": f"%{src_name}%"})

        # 公開觀測站 / MOPS：若使用者以 RSS 類型加入卻填了 mops.twse.com.tw，改為 mops 類型
        conn.execute(text(
            "UPDATE monitor_sources SET type = 'mops', "
            "url = 'https://mops.twse.com.tw/mops/web/t05sr01' "
            "WHERE type = 'rss' AND ("
            "  name LIKE '%公開%觀測%' OR name LIKE '%MOPS%' OR name LIKE '%重大訊息%'"
            "  OR url LIKE '%mops.twse.com.tw%'"
            ")"
        ))
        conn.commit()

        # 新增 White House 新聞稿（若不存在）
        wh_exists = conn.execute(text(
            "SELECT id FROM monitor_sources WHERE url LIKE '%whitehouse.gov%' LIMIT 1"
        )).fetchone()
        if not wh_exists:
            conn.execute(text(
                "INSERT INTO monitor_sources (name, type, url, keywords, is_active) VALUES "
                "('White House 新聞稿', 'rss', 'https://www.whitehouse.gov/feed/', "
                "'[\"tariff\",\"trade\",\"China\",\"Taiwan\",\"Fed\",\"economy\",\"sanction\",\"關稅\",\"貿易\"]', 0)"
            ))
        conn.commit()

        # ── 停用已確認失效的 RSS 來源（保留記錄，僅停用）──
        _broken_urls = [
            # IMF News: 403 blocked
            "https://www.imf.org/en/News/RSS",
            # World Bank: 404 URL changed
            "https://www.worldbank.org/en/rss/home",
            # 中央社財經: 404 URL deprecated
            "https://www.cna.com.tw/rss/financemarket.aspx",
            # Reuters: RSS service dead (000 connection refused)
            "https://feeds.reuters.com/reuters/businessNews",
            # 工商時報: 舊 URL https://ctee.com.tw/feed 連線拒絕，已遷移到官方 livenews RSS
            # （見下方 _ctee_migrate）— 不再列入 broken_urls，避免覆寫遷移後的有效 URL
            # 新浪財經: RSS discontinued (404)
            "https://rss.sina.com.cn/finance/forex/index.xml",
            "https://rss.sina.com.cn/finance/financenews/globalstock.xml",
            # AP Business: blocked from server IPs (000)
            "https://feeds.apnews.com/rss/apf-business",
            # OECD: 403 blocked
            "https://www.oecd.org/rss/newsroom.xml",
            # Caixin: 403 blocked
            "https://www.caixinglobal.com/rss",
            # PIIE: 403 blocked
            "https://www.piie.com/rss",
            # IMF Working Papers: 403 blocked
            "https://www.imf.org/en/Publications/RSS/all_papers",
            # ECB Working Papers: 404 URL changed
            "https://www.ecb.europa.eu/rss/wppubs.rss",
            # 台灣央行: HTML page (not RSS)
            "https://www.cbc.gov.tw/tw/cp-302-3364-B8157-1.html",
            # White House: 404
            "https://www.whitehouse.gov/feed/",
            # Berkshire: HTML page (not RSS)
            "https://www.berkshirehathaway.com/news/newsb.html",
        ]
        for _u in _broken_urls:
            conn.execute(text(
                "UPDATE monitor_sources SET is_active=0 WHERE url=:u"
            ), {"u": _u})
        # 鉅亨網 RSS 已停用 → 改用 JSON API（type="website"）
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 WHERE name LIKE '%鉅亨網%'"
        ))
        # 重新啟用三個主分類，指向有效的 JSON API 端點
        # 注意：headline URL 是 macro 後來遷移過來的最終位址
        _cnyes_api = [
            ("鉅亨網",
             "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock",
             '["台股","外資","法人","加權","漲","跌","ETF","台積","聯發","鴻海","大盤","台幣"]'),
            ("鉅亨網 - 總經",
             "https://api.cnyes.com/media/api/v1/newslist/category/headline",
             '["GDP","通膨","就業","利率","總經","央行","貨幣政策"]'),
            ("鉅亨網 - 美股",
             "https://news.cnyes.com/news/cat/wd_stock_all",
             '["美股","道瓊","納斯達克","標普","科技股","聯準會","AI","輝達","蘋果"]'),
        ]
        for _n, _u, _k in _cnyes_api:
            # 優先以 URL 查找（名稱可能已被使用者改動，URL 才是穩定識別鍵）
            _row = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url=:u LIMIT 1"
            ), {"u": _u}).fetchone()
            if _row:
                conn.execute(text(
                    "UPDATE monitor_sources SET type='website', is_active=1 "
                    "WHERE id=:i"
                ), {"i": _row[0]})
            else:
                # URL 不存在時，再嘗試以名稱查找（首次安裝時 URL 可能尚未設定）
                _row = conn.execute(text(
                    "SELECT id FROM monitor_sources WHERE name=:n LIMIT 1"
                ), {"n": _n}).fetchone()
                if _row:
                    conn.execute(text(
                        "UPDATE monitor_sources SET url=:u, type='website', is_active=1 "
                        "WHERE id=:i"
                    ), {"u": _u, "i": _row[0]})
                else:
                    conn.execute(text(
                        "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                        "VALUES (:n, 'website', :u, :k, 1)"
                    ), {"n": _n, "u": _u, "k": _k})
        # 清除因名稱遷移 bug 造成的鉅亨網 URL 重複條目（保留最舊的即使用者原始設定）
        _cnyes_dedup_urls = [
            "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock",
            "https://api.cnyes.com/media/api/v1/newslist/category/headline",
            "https://api.cnyes.com/media/api/v1/newslist/category/us_stock",
            "https://api.cnyes.com/media/api/v1/newslist/category/macro",
            "https://news.cnyes.com/news/cat/wd_stock_all",
        ]
        for _dup_url in _cnyes_dedup_urls:
            _dup_rows = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url=:u ORDER BY id ASC"
            ), {"u": _dup_url}).fetchall()
            if len(_dup_rows) > 1:
                for _dup in _dup_rows[1:]:  # 保留最舊的（id 最小），刪除後來插入的重複
                    conn.execute(text(
                        "DELETE FROM monitor_sources WHERE id=:i"
                    ), {"i": _dup[0]})
        conn.commit()

        # ── 工商時報遷移：舊 RSS URL 連線拒絕 → 改用官方 livenews RSS + 專屬爬蟲 ──
        # 處理時區（pubDate 無 tz 標記實為台灣時間），透過 ctee_scraper.py
        _ctee_new_url = "https://www.ctee.com.tw/rss_web/livenews/ctee"
        _ctee_old_urls = [
            "https://ctee.com.tw/feed",
            "https://www.ctee.com.tw/feed",
        ]
        _ctee_kw = '["台股","產業","法說會","獲利","投資"]'
        _ctee_existing = conn.execute(text(
            "SELECT id FROM monitor_sources WHERE url=:u LIMIT 1"
        ), {"u": _ctee_new_url}).fetchone()
        if _ctee_existing:
            conn.execute(text(
                "UPDATE monitor_sources SET type='website', is_active=1, is_deleted=0 WHERE id=:i"
            ), {"i": _ctee_existing[0]})
        else:
            _ctee_old = None
            for _u in _ctee_old_urls:
                _ctee_old = conn.execute(text(
                    "SELECT id FROM monitor_sources WHERE url=:u LIMIT 1"
                ), {"u": _u}).fetchone()
                if _ctee_old:
                    break
            if _ctee_old:
                conn.execute(text(
                    "UPDATE monitor_sources SET url=:u, type='website', is_active=1, is_deleted=0 WHERE id=:i"
                ), {"u": _ctee_new_url, "i": _ctee_old[0]})
            else:
                conn.execute(text(
                    "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                    "VALUES ('工商時報', 'website', :u, :k, 1)"
                ), {"u": _ctee_new_url, "k": _ctee_kw})
        # 清理其他舊 ctee 條目（GN 代理 / 舊 feed 等），避免重複抓取同來源
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0, is_deleted=1 "
            "WHERE url LIKE '%ctee.com.tw%' AND url <> :u"
        ), {"u": _ctee_new_url})
        conn.commit()

        # ── WSJ / Politico / NowNews 從 GN 代理（或失效直連）改為新直連，提升即時性 ──
        # 通用 helper：把所有符合任何 LIKE 模式的列遷移到 canonical 直連 URL
        # 1) 若已存在 canonical URL 列：啟用之
        # 2) 若不存在但有匹配舊列：把第一個改為 canonical
        # 3) 把其他匹配的舊列（GN 代理 / 失效直連 / 重複）軟刪除
        def _migrate_to_direct(like_patterns: list[str], canonical_url: str, src_type: str = "rss"):
            row = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url=:u LIMIT 1"
            ), {"u": canonical_url}).fetchone()
            if row:
                conn.execute(text(
                    "UPDATE monitor_sources SET type=:t, is_active=1, is_deleted=0 WHERE id=:i"
                ), {"t": src_type, "i": row[0]})
            else:
                for _p in like_patterns:
                    _old = conn.execute(text(
                        "SELECT id FROM monitor_sources WHERE url LIKE :p ORDER BY id LIMIT 1"
                    ), {"p": _p}).fetchone()
                    if _old:
                        conn.execute(text(
                            "UPDATE monitor_sources SET url=:u, type=:t, is_active=1, is_deleted=0 WHERE id=:i"
                        ), {"u": canonical_url, "t": src_type, "i": _old[0]})
                        break
            # 軟刪除其他所有符合 LIKE 但不是 canonical URL 的列（含 GN 代理、失效直連）
            for _p in like_patterns:
                conn.execute(text(
                    "UPDATE monitor_sources SET is_active=0, is_deleted=1 "
                    "WHERE url LIKE :p AND url <> :u"
                ), {"p": _p, "u": canonical_url})

        # WSJ：feeds.a.dj.com 自 2025/01 停更 → feeds.content.dowjones.io（>60 篇/更新頻繁）
        _migrate_to_direct(
            [
                "%news.google.com/rss/search%site:wsj.com%",
                "%feeds.a.dj.com%",
            ],
            "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
            "rss",
        )
        # Politico：原 economy.xml feed 已停止更新（最新 1 篇 4 月前）
        # → Morning Money（每日 8am ET 金融政策日報，30 篇）
        _migrate_to_direct(
            [
                "%news.google.com/rss/search%site:politico.com%",
                "%rss.politico.com/economy.xml%",
            ],
            "https://rss.politico.com/morningmoney.xml",
            "rss",
        )
        # NowNews：用 Google News Sitemap（含 <news:title> 與 publication_date）
        _migrate_to_direct(
            [
                "%news.google.com/rss/search%site:nownews.com%",
            ],
            "https://www.nownews.com/newsSitemap-daily.xml",
            "website",
        )
        # 風傳媒：原 sitemap 直連在 VM 被 CDN/WAF 擋 (403 Forbidden, IP-based 封鎖)
        # 本機開發測試 200，但 GCP us-east1 IP 全擋——只能改回 GN 代理
        _migrate_to_direct(
            [
                "%storm.mg/sitemaps%",
                "%storm.mg/article-news%",
            ],
            "https://news.google.com/rss/search?q=site:storm.mg+when:3d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
            "rss",
        )
        # US Treasury：home.treasury.gov/rss.xml 主要是行政頁面更新（非新聞稿）
        # → 改用 /news/press-releases HTML 列表頁，treasury_scraper 直接解析
        _migrate_to_direct(
            [
                "%news.google.com/rss/search%treasury.gov%",
                "%news.google.com/rss/search%us+treasury%",
                "%home.treasury.gov/rss.xml%",
            ],
            "https://home.treasury.gov/news/press-releases",
            "website",
        )
        conn.commit()

        # ── 新增可靠財金來源 v2（若不存在則插入）──
        _new_sources_v2 = [
            # 台灣補充
            ("自由時報財經", "rss",
             "https://news.ltn.com.tw/rss/business.xml",
             '["台股","台幣","產業","財經","匯率","外資","上市","上櫃"]', 1),
            ("MoneyDJ 財經知識庫", "rss",
             "https://www.moneydj.com/KMDJ/RSSService/RSS.aspx?cat=news",
             '["台股","ETF","基金","個股","法人","技術分析","台積","聯發"]', 1),
            ("鉅亨網 - 美股", "rss",
             "https://news.cnyes.com/rss/cat/us_stock",
             '["美股","道瓊","納斯達克","標普","科技股","聯準會","AI","輝達","蘋果"]', 1),
            # 國際通訊社 / 媒體
            ("AP Business", "rss",
             "https://feeds.apnews.com/rss/apf-business",
             '["economy","trade","tariff","Fed","inflation","market","recession","rate","debt"]', 1),
            ("Nikkei Asia", "rss",
             "https://asia.nikkei.com/rss/feed/nar",
             '["Asia","Japan","China","trade","economy","semiconductor","yen","BOJ","Taiwan"]', 1),
            ("South China Morning Post", "rss",
             "https://www.scmp.com/rss/91/feed",
             '["China","Hong Kong","yuan","economy","trade","PBOC","property","tariff"]', 1),
            ("The Guardian Business", "rss",
             "https://www.theguardian.com/uk/business/rss",
             '["economy","Europe","inflation","UK","interest rate","trade","recession","ECB"]', 1),
            ("Politico Morning Money", "rss",
             "https://rss.politico.com/morningmoney.xml",
             '["tariff","trade policy","Fed","sanction","debt","budget","economy","inflation"]', 1),
            # 能源 / 商品
            ("EIA Today in Energy", "rss",
             "https://www.eia.gov/rss/todayinenergy.xml",
             '["oil","crude","natural gas","OPEC","energy","petroleum","LNG","refinery"]', 1),
            ("OilPrice.com", "rss",
             "https://oilprice.com/rss/main",
             '["oil","OPEC","crude","energy","pipeline","supply","LNG","natural gas"]', 1),
            # 官方機構
            ("OECD Newsroom", "rss",
             "https://www.oecd.org/rss/newsroom.xml",
             '["OECD","GDP","growth","trade","inflation","interest rate","outlook","forecast"]', 1),
            # 中港
            ("財新 Caixin Global", "rss",
             "https://www.caixinglobal.com/rss",
             '["China","PBOC","yuan","economy","trade war","regulation","GDP","property","debt"]', 1),
        ]
        for _n, _t, _u, _k, _a in _new_sources_v2:
            _exists = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url = :u LIMIT 1"
            ), {"u": _u}).fetchone()
            if not _exists:
                conn.execute(text(
                    "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                    "VALUES (:n, :t, :u, :k, :a)"
                ), {"n": _n, "t": _t, "u": _u, "k": _k, "a": _a})
        conn.commit()

        # ── 新增研究機構 v2 ──
        _new_research_v2 = [
            ("NBER Working Papers",
             "https://www.nber.org/rss/new.xml",
             '["NBER","economics","monetary policy","fiscal","labor","finance","growth"]'),
            ("PIIE Research",
             "https://www.piie.com/rss",
             '["trade","tariff","global economy","sanctions","monetary","exchange rate","China"]'),
        ]
        for _n, _u, _k in _new_research_v2:
            # 同時檢查 URL 與名稱，避免前面的 migration UPDATE 改了 URL 後每次重啟都重複插入
            _exists = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url = :u OR (name = :n AND type = 'research') LIMIT 1"
            ), {"u": _u, "n": _n}).fetchone()
            if not _exists:
                conn.execute(text(
                    "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                    "VALUES (:n, 'research', :u, :k, 1)"
                ), {"n": _n, "u": _u, "k": _k})
        conn.commit()

        # ── 新增替代來源 v3（補充停用來源的覆蓋面）──
        _replacement_sources_v3 = [
            # Channel News Asia: 亞太區英文財經/政治新聞，覆蓋台灣、中國、東南亞
            ("Channel News Asia", "rss",
             "https://www.channelnewsasia.com/rssfeeds/8395744",
             '["Asia","economy","trade","Taiwan","China","US","market","central bank","Singapore","tariff"]', 1),
            # Yahoo Finance: 美國市場新聞，聚合 Reuters/AP/Bloomberg 內容
            ("Yahoo Finance", "rss",
             "https://finance.yahoo.com/rss/topstories",
             '["market","Fed","inflation","stocks","economy","rate","earnings","recession","tariff","trade"]', 1),
        ]
        for _n, _t, _u, _k, _a in _replacement_sources_v3:
            _exists = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url = :u LIMIT 1"
            ), {"u": _u}).fetchone()
            if not _exists:
                conn.execute(text(
                    "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                    "VALUES (:n, :t, :u, :k, :a)"
                ), {"n": _n, "t": _t, "u": _u, "k": _k, "a": _a})
        conn.commit()

        # ── 修復 NBER 重複資料（每次 migration UPDATE URL 後 _new_research_v2 會重插）──
        conn.execute(text(
            "DELETE FROM monitor_sources WHERE name='NBER Working Papers' AND type='research' "
            "AND id NOT IN ("
            "  SELECT MIN(id) FROM monitor_sources WHERE name='NBER Working Papers' AND type='research'"
            ")"
        ))
        conn.commit()

        # ── 新增可靠財金來源 v4 ──
        # 台灣央行 (CBC)：修正 RSS URL 或新增（舊 URL 是 HTML 頁，正確 RSS 在 rss-302-1.xml）
        _cbc_rss_url = "https://www.cbc.gov.tw/tw/rss-302-1.xml"
        _cbc_existing = conn.execute(text(
            "SELECT id FROM monitor_sources WHERE url LIKE '%cbc.gov.tw%' LIMIT 1"
        )).fetchone()
        if _cbc_existing:
            conn.execute(text(
                "UPDATE monitor_sources SET url=:u, is_active=1 WHERE id=:i"
            ), {"u": _cbc_rss_url, "i": _cbc_existing[0]})
        else:
            conn.execute(text(
                "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                "VALUES ('台灣央行新聞稿 (CBC)', 'rss', :u, "
                "'[\"央行\",\"利率\",\"貨幣政策\",\"外匯\",\"台幣\",\"通膨\",\"金融穩定\",\"理監事會\"]', 1)"
            ), {"u": _cbc_rss_url})
        conn.commit()

        # 清除鉅亨網舊 RSS 條目（404 路徑，已被 website 型 JSON API 取代）
        conn.execute(text(
            "DELETE FROM monitor_sources WHERE url LIKE '%news.cnyes.com/rss%' AND type='rss'"
        ))
        conn.commit()

        # MoneyDJ：舊 KMDJ/RSSService/RSS.aspx 路徑已棄用，改為正確的 RssCenter 端點
        _moneydj_new_url = "https://www.moneydj.com/kmdj/RssCenter.aspx?svc=NW&fno=1&arg=X0000000"
        conn.execute(text(
            "UPDATE monitor_sources SET url=:u "
            "WHERE url LIKE '%moneydj.com%RSSService%' OR url LIKE '%moneydj.com%RSS.aspx%'"
        ), {"u": _moneydj_new_url})
        # MoneyDJ 去重：若因 UPDATE 產生重複，保留最舊的一筆
        conn.execute(text(
            "DELETE FROM monitor_sources WHERE url=:u "
            "AND id NOT IN (SELECT MIN(id) FROM monitor_sources WHERE url=:u)"
        ), {"u": _moneydj_new_url})
        # FSC 金管會 RSS：所有 /rss/*.xml 路徑皆回傳 HTML（服務失效），改為停用
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE url LIKE '%fsc.gov.tw/rss%'"
        ))
        conn.commit()

        _new_sources_v4 = [
            # Yahoo 奇摩台灣股市新聞（包含 tw.stock.yahoo.com 文章）
            ("Yahoo 台灣財經新聞", "rss",
             "https://tw.news.yahoo.com/rss/",
             '["台股","台灣","財經","外資","漲","跌","法人","ETF","大盤","匯率","央行"]', 1),
            # 日經中文網（覆蓋日本/亞洲金融、中日台相關）
            ("日經中文網", "rss",
             "https://zh.cn.nikkei.com/rss.html",
             '["日本","亞洲","日圓","日銀","BOJ","中國","台灣","半導體","貿易","關稅","美日"]', 1),
            # 證券期貨局 (SFB) 新聞稿
            ("證券期貨局新聞稿 (SFB)", "rss",
             "https://www.sfb.gov.tw/RSS/sfb/Messages?serno=201501270006&language=chinese",
             '["證券","期貨","上市","上櫃","裁罰","監理","法規","財報","投資人","違規"]', 1),
        ]
        for _n, _t, _u, _k, _a in _new_sources_v4:
            _exists = conn.execute(text(
                "SELECT id FROM monitor_sources WHERE url = :u LIMIT 1"
            ), {"u": _u}).fetchone()
            if not _exists:
                conn.execute(text(
                    "INSERT INTO monitor_sources (name, type, url, keywords, is_active) "
                    "VALUES (:n, :t, :u, :k, :a)"
                ), {"n": _n, "t": _t, "u": _u, "k": _k, "a": _a})
        conn.commit()

        # ── v5: 清理重複來源 + 修正失效 + 恢復已正常來源 ──
        # 刪除重複 MOPS 條目（同 URL 只保留 id 最小的）
        conn.execute(text(
            "DELETE FROM monitor_sources WHERE type='mops' "
            "AND id NOT IN (SELECT MIN(id) FROM monitor_sources WHERE type='mops')"
        ))
        # 刪除 UDN 經濟日報（money.udn.com RSS 永遠 0 篇，feed 無 item，已確認無效）
        conn.execute(text(
            "DELETE FROM monitor_sources WHERE url='https://money.udn.com/rssfeed/news/1/5591'"
        ))
        # BIS 新聞 RSS：/rss/index.htm 現在回傳 HTML，停用
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 WHERE url='https://www.bis.org/rss/index.htm'"
        ))
        # 鉅亨網 - 總經：macro 分類 API 已停用(422)，改用 headline（頭條）
        conn.execute(text(
            "UPDATE monitor_sources SET "
            "url='https://api.cnyes.com/media/api/v1/newslist/category/headline' "
            "WHERE url='https://api.cnyes.com/media/api/v1/newslist/category/macro'"
        ))
        # 恢復已確認正常的來源（SCMP / Nikkei Asia；US Treasury 已遷移到 /news/press-releases）
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=1 WHERE url IN ("
            "  'https://www.scmp.com/rss/91/feed',"
            "  'https://asia.nikkei.com/rss/feed/nar'"
            ")"
        ))
        # WSJ：舊 feeds.a.dj.com 自 2025/01 起停止更新；改用 Dow Jones 公開 RSS
        # （feeds.content.dowjones.io 仍有更新，>60 篇/分鐘級即時性）
        conn.execute(text(
            "UPDATE monitor_sources SET "
            "url='https://feeds.content.dowjones.io/public/rss/RSSMarketsMain', "
            "name='Wall Street Journal' "
            "WHERE url LIKE '%feeds.a.dj.com%'"
        ))
        conn.commit()

        # Backfill min_severity into existing LINE notification setting if missing
        import json as _json
        row = conn.execute(text(
            "SELECT id, config FROM notification_settings WHERE channel = 'line'"
        )).fetchone()
        if row:
            try:
                cfg = _json.loads(row[1]) if row[1] else {}
            except Exception:
                cfg = {}
            if "min_severity" not in cfg:
                cfg["min_severity"] = "critical"
                conn.execute(
                    text("UPDATE notification_settings SET config = :c WHERE id = :i"),
                    {"c": _json.dumps(cfg), "i": row[0]},
                )
                conn.commit()

        # 新增 Article 四維評分欄位 + matched_keyword（本地計算，無 API 呼叫）
        for _col in [
            "composite_score REAL",
            "finance_relevance REAL",
            "novelty_score REAL",
            "decay_factor REAL",
            "intensity_score REAL",
            "matched_keyword VARCHAR",
            "severity VARCHAR",
        ]:
            try:
                conn.execute(text(f"ALTER TABLE articles ADD COLUMN {_col}"))
                conn.commit()
            except Exception:
                pass  # 欄位已存在，略過

        # 新增 MonitorSource.fetch_all（全文讀取：跳過關鍵字過濾）
        try:
            conn.execute(text("ALTER TABLE monitor_sources ADD COLUMN fetch_all BOOLEAN DEFAULT 0"))
            conn.commit()
        except Exception:
            pass  # 欄位已存在，略過

        # 新增 MonitorSource.fixed_severity（來源級別強制風險等級）
        try:
            conn.execute(text("ALTER TABLE monitor_sources ADD COLUMN fixed_severity VARCHAR"))
            conn.commit()
        except Exception:
            pass  # 欄位已存在，略過

        # 新增 MonitorSource.sort_order（使用者自訂排序）
        try:
            conn.execute(text("ALTER TABLE monitor_sources ADD COLUMN sort_order INTEGER DEFAULT 0"))
            conn.commit()
        except Exception:
            pass  # 欄位已存在，略過

        # 新增 MonitorSource 健康監控三欄位（last_attempt_at / last_success_at / last_error）
        for _col_sql in (
            "ALTER TABLE monitor_sources ADD COLUMN last_attempt_at DATETIME",
            "ALTER TABLE monitor_sources ADD COLUMN last_success_at DATETIME",
            "ALTER TABLE monitor_sources ADD COLUMN last_error VARCHAR(500)",
        ):
            try:
                conn.execute(text(_col_sql))
                conn.commit()
            except Exception:
                pass  # 欄位已存在，略過
        # 初始化 sort_order（依現有 id 順序，只更新 sort_order=0 的列）
        conn.execute(text("""
            UPDATE monitor_sources
            SET sort_order = (
                SELECT COUNT(*) FROM monitor_sources m2 WHERE m2.id < monitor_sources.id
            )
            WHERE sort_order = 0 OR sort_order IS NULL
        """))
        conn.commit()

        # ── v6: 修正來源 type，使其對應正確的爬蟲處理器 ──
        # 注意：只更新 type 和 url（技術欄位），不覆蓋使用者可自訂的欄位
        #（name, is_active, fetch_all, fixed_severity, keywords, sort_order）
        # World Bank：舊 RSS (404) → 新 JSON API + website type（worldbank_scraper）
        conn.execute(text(
            "UPDATE monitor_sources SET "
            "type='website', "
            "url='https://search.worldbank.org/api/v2/news?format=json&rows=30&os=0' "
            "WHERE (name LIKE '%World Bank%' OR name LIKE '%世界銀行%') "
            "AND type='rss'"
        ))
        # FSC 金管會：RSS 已失效 → HTML 爬蟲 + website type（fsc_scraper）
        conn.execute(text(
            "UPDATE monitor_sources SET "
            "type='website', "
            "url='https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2&mcustomize=news_list.jsp' "
            "WHERE (name LIKE '%FSC%' OR name LIKE '%金管會%') "
            "AND type='rss'"
        ))
        # Caixin 財新：RSS 403 → HTML 爬蟲 + website type（caixin_scraper）
        # 停用舊 RSS 條目
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0 "
            "WHERE url='https://www.caixinglobal.com/rss'"
        ))
        # 確保 /news/ 版本存在（只在不存在時 INSERT，不覆蓋現有設定）
        _caixin_web = conn.execute(text(
            "SELECT id FROM monitor_sources WHERE url='https://www.caixinglobal.com/news/' LIMIT 1"
        )).fetchone()
        if _caixin_web:
            # 只修正 type（技術欄位），不碰 name / fetch_all / is_active 等使用者自訂值
            conn.execute(text(
                "UPDATE monitor_sources SET type='website' WHERE id=:i AND type != 'website'"
            ), {"i": _caixin_web[0]})
        else:
            conn.execute(text(
                "INSERT INTO monitor_sources (name, type, url, keywords, is_active, fetch_all) VALUES "
                "('財新 Caixin Global', 'website', 'https://www.caixinglobal.com/news/', "
                "'[\"China\",\"PBOC\",\"yuan\",\"economy\",\"trade\",\"regulation\",\"GDP\",\"property\",\"debt\"]', 1, 1)"
            ))
        conn.commit()

        # ── NLM 分析報告歷史記錄表（累積保存，不覆蓋）──
        conn.execute(text("""CREATE TABLE IF NOT EXISTS nlm_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT DEFAULT 'news',
            content TEXT,
            generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_title TEXT)"""))
        conn.commit()

        # ── v7: 軟刪除支援 + 清理重複來源 ──
        # 新增 is_deleted 欄位（使用者刪除後設為 True，migration 不重新插入）
        try:
            conn.execute(text(
                "ALTER TABLE monitor_sources ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            pass  # 欄位已存在，略過

        # 清理重複 FSC 來源（同 URL 保留 id 最小者）
        conn.execute(text("""
            DELETE FROM monitor_sources
            WHERE url = 'https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2&mcustomize=news_list.jsp'
            AND id NOT IN (
                SELECT MIN(id) FROM monitor_sources
                WHERE url = 'https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2&mcustomize=news_list.jsp'
            )
        """))
        # 清理重複 Caixin RSS 來源（已停用的舊版）
        conn.execute(text(
            "DELETE FROM monitor_sources WHERE url='https://www.caixinglobal.com/rss' AND is_active=0"
        ))
        # 軟刪除舊版 Truth Social RSS（403 錯誤，改用 trumpstruth.org feed）
        conn.execute(text(
            "UPDATE monitor_sources SET is_active=0, is_deleted=1 "
            "WHERE url LIKE '%truthsocial.com%' AND is_deleted=0"
        ))
        conn.commit()


def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_defaults():
    """Seed default market watchlist and monitor sources."""
    db = SessionLocal()
    try:
        # Seed market watchlist if empty
        if db.query(MarketWatchItem).count() == 0:
            defaults = [
                # Equity (股市)
                MarketWatchItem(symbol="^TWII", name="台股加權指數", category="equity", description="台灣證券交易所加權股價指數", sort_order=0),
                MarketWatchItem(symbol="^GSPC", name="S&P 500", category="equity", description="美國標準普爾500指數", sort_order=1),
                MarketWatchItem(symbol="^DJI", name="道瓊工業指數", category="equity", description="道瓊斯工業平均指數", sort_order=2),
                MarketWatchItem(symbol="^IXIC", name="那斯達克指數", category="equity", description="那斯達克綜合指數", sort_order=3),
                # Bond (債市)
                MarketWatchItem(symbol="^TNX", name="美10Y殖利率", category="bond", description="美國10年期公債殖利率", sort_order=0),
                MarketWatchItem(symbol="^FVX", name="美5Y殖利率", category="bond", description="美國5年期公債殖利率", sort_order=1),
                MarketWatchItem(symbol="^TYX", name="美30Y殖利率", category="bond", description="美國30年期公債殖利率", sort_order=2),
                # Currency (匯市)
                MarketWatchItem(symbol="DX-Y.NYB", name="美元指數", category="currency", description="美元指數 (DXY)", sort_order=0),
                MarketWatchItem(symbol="EURUSD=X", name="歐元/美元", category="currency", description="歐元兌美元匯率", sort_order=1),
                MarketWatchItem(symbol="JPY=X", name="美元/日圓", category="currency", description="美元兌日圓匯率", sort_order=2),
                MarketWatchItem(symbol="TWD=X", name="美元/台幣", category="currency", description="美元兌新台幣匯率", sort_order=3),
                # Commodity (原物料)
                MarketWatchItem(symbol="GC=F", name="黃金期貨", category="commodity", description="COMEX黃金期貨", sort_order=0),
                MarketWatchItem(symbol="CL=F", name="原油期貨", category="commodity", description="WTI原油期貨", sort_order=1),
                MarketWatchItem(symbol="SI=F", name="白銀期貨", category="commodity", description="COMEX白銀期貨", sort_order=2),
                # Crypto (加密貨幣)
                MarketWatchItem(symbol="BTC-USD", name="比特幣", category="crypto", description="比特幣/美元", sort_order=0),
                MarketWatchItem(symbol="ETH-USD", name="以太幣", category="crypto", description="以太幣/美元", sort_order=1),
                # Volatility (波動率)
                MarketWatchItem(symbol="^VIX", name="VIX 恐慌指數", category="volatility", description="CBOE波動率指數", threshold_upper=25, sort_order=0),
            ]
            db.add_all(defaults)
            db.flush()  # get IDs for signal conditions

            # Seed default signal conditions
            vix_item = db.query(MarketWatchItem).filter(MarketWatchItem.symbol == "^VIX").first()
            tnx_item = db.query(MarketWatchItem).filter(MarketWatchItem.symbol == "^TNX").first()

            conditions = []
            if vix_item:
                conditions.extend([
                    SignalCondition(watchlist_id=vix_item.id, name="恐慌區間", operator="gt", value=25,
                                    signal="negative", message="VIX > 25，市場恐慌升高", priority=1),
                    SignalCondition(watchlist_id=vix_item.id, name="警戒區間", operator="gt", value=20,
                                    signal="neutral", message="VIX > 20，留意市場波動", priority=2),
                    SignalCondition(watchlist_id=vix_item.id, name="穩定區間", operator="lt", value=15,
                                    signal="positive", message="VIX < 15，市場情緒穩定", priority=3),
                ])
            if tnx_item:
                conditions.extend([
                    SignalCondition(watchlist_id=tnx_item.id, name="高利率警示", operator="gt", value=5.0,
                                    signal="negative", message="10Y殖利率 > 5%，高利率環境", priority=1),
                    SignalCondition(watchlist_id=tnx_item.id, name="利率上升", operator="gt", value=4.5,
                                    signal="neutral", message="10Y殖利率 > 4.5%，留意利率風險", priority=2),
                ])
            if conditions:
                db.add_all(conditions)

        # Seed monitor sources if empty
        if db.query(MonitorSource).count() == 0:
            sources = [
                MonitorSource(
                    name="聯準會 (Fed)",
                    type="rss",
                    url="https://www.federalreserve.gov/feeds/press_all.xml",
                    keywords='["Fed","FOMC","利率","升息","降息"]',
                ),
                MonitorSource(
                    name="歐洲央行 (ECB)",
                    type="rss",
                    url="https://www.ecb.europa.eu/rss/press.html",
                    keywords='["ECB","歐元","利率"]',
                ),
                MonitorSource(
                    name="Bloomberg Markets",
                    type="rss",
                    url="https://feeds.bloomberg.com/markets/news.rss",
                    keywords='["market","股市","債券"]',
                ),
                MonitorSource(
                    name="CNBC Business",
                    type="rss",
                    url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147",
                    keywords='["economy","trade","Fed","market"]',
                ),
                MonitorSource(
                    name="日本央行 (BOJ)",
                    type="rss",
                    url="https://www.boj.or.jp/en/rss/whatsnew.xml",
                    keywords='["BOJ","日本央行","yen","利率","円"]',
                ),
                MonitorSource(
                    name="IMF",
                    type="rss",
                    url="https://www.imf.org/en/News/RSS",
                    keywords='["IMF","global economy","growth","debt"]',
                    is_active=False,  # 403 blocked — re-enable if URL is fixed
                ),
                MonitorSource(
                    name="World Bank",
                    type="rss",
                    url="https://www.worldbank.org/en/rss/home",
                    keywords='["development","emerging","growth"]',
                    is_active=False,  # 404 URL deprecated — re-enable if URL is fixed
                ),
                MonitorSource(
                    name="Financial Times",
                    type="rss",
                    url="https://www.ft.com/rss/home",
                    keywords='["market","economy","trade","central bank"]',
                ),
                MonitorSource(
                    name="Wall Street Journal",
                    type="rss",
                    url="https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
                    keywords='["market","stocks","bonds","Fed","economy"]',
                ),
                MonitorSource(
                    name="金管會新聞稿 (FSC)",
                    type="rss",
                    url="https://www.fsc.gov.tw/rss/rss_news.xml",
                    keywords='["金管會","銀行","保險","證券","監理","FSC"]',
                ),
                MonitorSource(
                    name="中央社財經",
                    type="rss",
                    url="https://www.cna.com.tw/rss/financemarket.aspx",
                    keywords='["台股","外資","法人","央行","利率","匯率"]',
                    is_active=False,  # 404 RSS deprecated — re-enable if URL is fixed
                ),
                MonitorSource(
                    name="公開資訊觀測站重大訊息",
                    type="mops",
                    url="https://mops.twse.com.tw/mops/web/t05sr01",
                    keywords='["重大訊息","重訊","法說","盈餘"]',
                    is_active=True,
                ),
                MonitorSource(
                    name="Reuters Business",
                    type="rss",
                    url="https://feeds.reuters.com/reuters/businessNews",
                    keywords='["business","trade","economy","market"]',
                    is_active=False,  # Reuters RSS service dead (000 connection refused)
                ),
                # ── 台灣國內來源 ──
                MonitorSource(
                    name="經濟日報",
                    type="rss",
                    url="https://money.udn.com/rssfeed/news/1/5591",
                    keywords='["台股","台幣","央行","利率","外資"]',
                ),
                MonitorSource(
                    name="工商時報",
                    type="website",
                    url="https://www.ctee.com.tw/rss_web/livenews/ctee",
                    keywords='["台股","產業","法說會","獲利","投資"]',
                ),
                MonitorSource(
                    name="鉅亨網",
                    type="website",
                    url="https://api.cnyes.com/media/api/v1/newslist/category/tw_stock",
                    keywords='["台股","外資","法人","加權","漲","跌","ETF","台積","聯發","鴻海","大盤","台幣"]',
                ),
                MonitorSource(
                    name="台灣央行 (CBC)",
                    type="rss",
                    url="https://www.cbc.gov.tw/tw/cp-302-3364-B8157-1.html",
                    keywords='["利率","貨幣政策","通膨","外匯","台幣"]',
                    is_active=False,  # HTML 頁面非 RSS — 請更換正確 RSS URL
                ),
                MonitorSource(
                    name="鉅亨網 - 總經",
                    type="website",
                    url="https://api.cnyes.com/media/api/v1/newslist/category/macro",
                    keywords='["GDP","通膨","就業","利率","總經","央行","貨幣政策"]',
                ),
                # ── 國際擴充 ──
                MonitorSource(
                    name="MarketWatch",
                    type="rss",
                    url="https://feeds.marketwatch.com/marketwatch/topstories/",
                    keywords='["Fed","inflation","market","stocks","recession"]',
                ),
                MonitorSource(
                    name="BIS（國際清算銀行）",
                    type="rss",
                    url="https://www.bis.org/rss/index.htm",
                    keywords='["central bank","policy","financial stability","rate"]',
                ),
                MonitorSource(
                    name="Bank of England (BOE)",
                    type="rss",
                    url="https://www.bankofengland.co.uk/rss/news",
                    keywords='["BOE","sterling","UK rate","gilts"]',
                ),
                MonitorSource(
                    name="US Treasury",
                    type="website",
                    url="https://home.treasury.gov/news/press-releases",
                    keywords='["yield","TGA","debt","sanctions","Treasury"]',
                ),
                MonitorSource(
                    name="新浪財經 - 外匯",
                    type="rss",
                    url="https://rss.sina.com.cn/finance/forex/index.xml",
                    keywords='["人民幣","外匯","央行","降準","匯率"]',
                    is_active=False,  # RSS 已停用 (404)
                ),
                MonitorSource(
                    name="新浪財經",
                    type="rss",
                    url="https://rss.sina.com.cn/finance/financenews/globalstock.xml",
                    keywords='["A股","滬深","港股","人民幣","中概股"]',
                    is_active=False,  # RSS 已停用 (404)
                ),
                MonitorSource(
                    name="Investing.com",
                    type="rss",
                    url="https://www.investing.com/rss/news.rss",
                    keywords='["market","commodity","currency","rate","Fed"]',
                ),
                # ── 特定人物 / 社群帳號 ──
                # Trump Truth Social（透過 trumpstruth.org 第三方 feed）
                # 備用方案：White House → https://www.whitehouse.gov/feed/
                MonitorSource(
                    name="@realDonaldTrump",
                    type="social",
                    url="https://www.trumpstruth.org/feed",
                    keywords='["Trump","tariff","trade war","Fed","China","Taiwan","關稅","貿易戰"]',
                    is_active=False,  # 預設停用，請先測試 RSS 後再啟用
                ),
                MonitorSource(
                    name="White House 新聞稿",
                    type="rss",
                    url="https://www.whitehouse.gov/feed/",
                    keywords='["tariff","trade","China","Taiwan","Fed","economy","sanction","關稅","貿易"]',
                    is_active=False,
                ),
                MonitorSource(
                    name="Fed 官員演講（Powell 等）",
                    type="person",
                    url="https://www.federalreserve.gov/feeds/speeches.xml",
                    keywords='["Powell","Fed","interest rate","monetary policy","inflation"]',
                ),
                MonitorSource(
                    name="ECB 官員演講（Lagarde 等）",
                    type="person",
                    url="https://www.ecb.europa.eu/rss/press.html",
                    keywords='["Lagarde","ECB","euro","rate","inflation"]',
                ),
                MonitorSource(
                    name="Warren Buffett / Berkshire",
                    type="person",
                    url="https://www.berkshirehathaway.com/news/newsb.html",
                    keywords='["Buffett","Berkshire","investment","portfolio"]',
                    is_active=False,  # HTML 頁面非 RSS feed
                ),
                # ── 台灣補充 ──
                MonitorSource(
                    name="自由時報財經",
                    type="rss",
                    url="https://news.ltn.com.tw/rss/business.xml",
                    keywords='["台股","台幣","產業","財經","匯率","外資","上市","上櫃"]',
                ),
                MonitorSource(
                    name="MoneyDJ 財經知識庫",
                    type="rss",
                    url="https://www.moneydj.com/KMDJ/RSSService/RSS.aspx?cat=news",
                    keywords='["台股","ETF","基金","個股","法人","技術分析","台積","聯發"]',
                ),
                MonitorSource(
                    name="鉅亨網 - 美股",
                    type="website",
                    url="https://api.cnyes.com/media/api/v1/newslist/category/us_stock",
                    keywords='["美股","道瓊","納斯達克","標普","科技股","聯準會","AI","輝達","蘋果"]',
                ),
                # ── 國際通訊社 / 媒體 ──
                MonitorSource(
                    name="AP Business",
                    type="rss",
                    url="https://feeds.apnews.com/rss/apf-business",
                    keywords='["economy","trade","tariff","Fed","inflation","market","recession","rate","debt"]',
                ),
                MonitorSource(
                    name="Nikkei Asia",
                    type="rss",
                    url="https://asia.nikkei.com/rss/feed/nar",
                    keywords='["Asia","Japan","China","trade","economy","semiconductor","yen","BOJ","Taiwan"]',
                ),
                MonitorSource(
                    name="South China Morning Post",
                    type="rss",
                    url="https://www.scmp.com/rss/91/feed",
                    keywords='["China","Hong Kong","yuan","economy","trade","PBOC","property","tariff"]',
                ),
                MonitorSource(
                    name="The Guardian Business",
                    type="rss",
                    url="https://www.theguardian.com/uk/business/rss",
                    keywords='["economy","Europe","inflation","UK","interest rate","trade","recession","ECB"]',
                ),
                MonitorSource(
                    name="Politico Morning Money",
                    type="rss",
                    url="https://rss.politico.com/morningmoney.xml",
                    keywords='["tariff","trade policy","Fed","sanction","debt","budget","economy","inflation"]',
                ),
                # ── 能源 / 商品 ──
                MonitorSource(
                    name="EIA Today in Energy",
                    type="rss",
                    url="https://www.eia.gov/rss/todayinenergy.xml",
                    keywords='["oil","crude","natural gas","OPEC","energy","petroleum","LNG","refinery"]',
                ),
                MonitorSource(
                    name="OilPrice.com",
                    type="rss",
                    url="https://oilprice.com/rss/main",
                    keywords='["oil","OPEC","crude","energy","pipeline","supply","LNG","natural gas"]',
                ),
                # ── 官方機構補充 ──
                MonitorSource(
                    name="OECD Newsroom",
                    type="rss",
                    url="https://www.oecd.org/rss/newsroom.xml",
                    keywords='["OECD","GDP","growth","trade","inflation","interest rate","outlook","forecast"]',
                    is_active=False,  # 403 blocked
                ),
                # ── 中港 ──
                MonitorSource(
                    name="財新 Caixin Global",
                    type="rss",
                    url="https://www.caixinglobal.com/rss",
                    keywords='["China","PBOC","yuan","economy","trade war","regulation","GDP","property","debt"]',
                    is_active=False,  # 403 blocked
                ),
                # ── 替代：亞太 / 美國市場 ──
                MonitorSource(
                    name="Channel News Asia",
                    type="rss",
                    url="https://www.channelnewsasia.com/rssfeeds/8395744",
                    keywords='["Asia","economy","trade","Taiwan","China","US","market","central bank","Singapore","tariff"]',
                ),
                MonitorSource(
                    name="Yahoo Finance",
                    type="rss",
                    url="https://finance.yahoo.com/rss/topstories",
                    keywords='["market","Fed","inflation","stocks","economy","rate","earnings","recession","tariff","trade"]',
                ),
            ]
            db.add_all(sources)

        # Seed research sources if none exist
        if db.query(MonitorSource).filter(MonitorSource.type == "research").count() == 0:
            research_sources = [
                MonitorSource(name="IMF Working Papers", type="research",
                    url="https://www.imf.org/en/Publications/RSS/all_papers",
                    keywords='["IMF","monetary","fiscal","global economy"]', is_active=False),  # 403 blocked
                MonitorSource(name="BIS Working Papers", type="research",
                    url="https://www.bis.org/doclist/wppubls.rss",
                    keywords='["BIS","central bank","financial stability","monetary policy"]', is_active=True),
                MonitorSource(name="Fed FEDS Notes", type="research",
                    url="https://www.federalreserve.gov/feeds/FEDS_notes.xml",
                    keywords='["Fed","monetary policy","inflation","interest rate"]', is_active=True),
                MonitorSource(name="ECB Working Papers", type="research",
                    url="https://www.ecb.europa.eu/rss/wppubs.rss",
                    keywords='["ECB","euro","monetary policy","inflation"]', is_active=False),  # 404 URL deprecated
                MonitorSource(name="BOJ Research", type="research",
                    url="https://www.boj.or.jp/en/rss/whatsnew.xml",
                    keywords='["BOJ","Japan","monetary policy","yen"]', is_active=True),
                MonitorSource(name="BOE Staff WP", type="research",
                    url="https://www.bankofengland.co.uk/rss/publications",
                    keywords='["BOE","UK","monetary policy","sterling"]', is_active=True),
                MonitorSource(name="NBER Working Papers", type="research",
                    url="https://www.nber.org/rss/new.xml",
                    keywords='["NBER","economics","monetary policy","fiscal","labor","finance","growth"]', is_active=True),
                MonitorSource(name="PIIE Research", type="research",
                    url="https://www.piie.com/rss",
                    keywords='["trade","tariff","global economy","sanctions","monetary","exchange rate","China"]', is_active=False),  # 403 blocked
            ]
            db.add_all(research_sources)

        # Seed notification settings if empty
        if db.query(NotificationSetting).count() == 0:
            notifs = [
                NotificationSetting(channel="web", is_enabled=True, config="{}"),
                NotificationSetting(channel="line", is_enabled=False, config='{"token":"","min_severity":"critical"}'),
                NotificationSetting(channel="email", is_enabled=False, config='{"recipient":""}'),
                NotificationSetting(channel="discord", is_enabled=False, config='{"webhook_url":""}'),
            ]
            db.add_all(notifs)
        else:
            # 新版本補建缺少的管道（不清除現有資料）
            existing_channels = {r.channel for r in db.query(NotificationSetting).all()}
            missing = []
            if "discord" not in existing_channels:
                missing.append(NotificationSetting(channel="discord", is_enabled=False, config='{"webhook_url":""}'))
            if missing:
                db.add_all(missing)

        db.commit()
    finally:
        db.close()
