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
                text("SELECT id FROM monitor_sources WHERE name = :n AND type = 'research'"),
                {"n": name}
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
                ),
                MonitorSource(
                    name="World Bank",
                    type="rss",
                    url="https://www.worldbank.org/en/rss/home",
                    keywords='["development","emerging","growth"]',
                ),
                MonitorSource(
                    name="Financial Times",
                    type="rss",
                    url="https://www.ft.com/rss/home",
                    keywords='["market","economy","trade","central bank"]',
                ),
                MonitorSource(
                    name="Wall Street Journal Markets",
                    type="rss",
                    url="https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
                    keywords='["market","stocks","bonds","Fed","economy"]',
                ),
                MonitorSource(
                    name="台灣金管會",
                    type="rss",
                    url="https://www.fsc.gov.tw/ch/home.jsp?id=125&parentpath=0,5",
                    keywords='["金管會","銀行","保險","證券","監理"]',
                ),
                MonitorSource(
                    name="Reuters Business",
                    type="rss",
                    url="https://feeds.reuters.com/reuters/businessNews",
                    keywords='["business","trade","economy","market"]',
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
                    type="rss",
                    url="https://ctee.com.tw/feed",
                    keywords='["台股","產業","法說會","獲利","投資"]',
                ),
                MonitorSource(
                    name="鉅亨網",
                    type="rss",
                    url="https://news.cnyes.com/rss/cat/index",
                    keywords='["台股","外資","法人","指數","漲跌"]',
                ),
                MonitorSource(
                    name="台灣央行 (CBC)",
                    type="rss",
                    url="https://www.cbc.gov.tw/tw/cp-302-3364-B8157-1.html",
                    keywords='["利率","貨幣政策","通膨","外匯","台幣"]',
                ),
                MonitorSource(
                    name="鉅亨網 - 總經",
                    type="rss",
                    url="https://news.cnyes.com/rss/cat/macro",
                    keywords='["GDP","通膨","就業","利率","總經"]',
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
                    type="rss",
                    url="https://home.treasury.gov/rss.xml",
                    keywords='["yield","TGA","debt","sanctions","Treasury"]',
                ),
                MonitorSource(
                    name="新浪財經 - 外匯",
                    type="rss",
                    url="https://rss.sina.com.cn/finance/forex/index.xml",
                    keywords='["人民幣","外匯","央行","降準","匯率"]',
                ),
                MonitorSource(
                    name="新浪財經",
                    type="rss",
                    url="https://rss.sina.com.cn/finance/financenews/globalstock.xml",
                    keywords='["A股","滬深","港股","人民幣","中概股"]',
                ),
                MonitorSource(
                    name="Investing.com",
                    type="rss",
                    url="https://www.investing.com/rss/news.rss",
                    keywords='["market","commodity","currency","rate","Fed"]',
                ),
                # ── 特定人物 / 央行演講（RSS 鏡像，無需 Twitter API）──
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
                ),
            ]
            db.add_all(sources)

        # Seed research sources if none exist
        if db.query(MonitorSource).filter(MonitorSource.type == "research").count() == 0:
            research_sources = [
                MonitorSource(name="IMF Working Papers", type="research",
                    url="https://www.imf.org/en/Publications/RSS/all_papers",
                    keywords='["IMF","monetary","fiscal","global economy"]', is_active=True),
                MonitorSource(name="BIS Working Papers", type="research",
                    url="https://www.bis.org/doclist/wppubls.rss",
                    keywords='["BIS","central bank","financial stability","monetary policy"]', is_active=True),
                MonitorSource(name="Fed FEDS Notes", type="research",
                    url="https://www.federalreserve.gov/feeds/FEDS_notes.xml",
                    keywords='["Fed","monetary policy","inflation","interest rate"]', is_active=True),
                MonitorSource(name="ECB Working Papers", type="research",
                    url="https://www.ecb.europa.eu/rss/wppubs.rss",
                    keywords='["ECB","euro","monetary policy","inflation"]', is_active=True),
                MonitorSource(name="BOJ Research", type="research",
                    url="https://www.boj.or.jp/en/rss/whatsnew.xml",
                    keywords='["BOJ","Japan","monetary policy","yen"]', is_active=True),
                MonitorSource(name="BOE Staff WP", type="research",
                    url="https://www.bankofengland.co.uk/rss/publications",
                    keywords='["BOE","UK","monetary policy","sterling"]', is_active=True),
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
