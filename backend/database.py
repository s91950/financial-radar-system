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


# --- Database Helpers ---

def init_db():
    """Create all tables and seed default data."""
    Base.metadata.create_all(bind=engine)
    _seed_defaults()


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
                    url="https://blogs.worldbank.org/feed",
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
                    url="https://www.fsc.gov.tw/fckdowndoc?file=/rss/news_rss.xml",
                    keywords='["金管會","銀行","保險","證券","監理"]',
                ),
                MonitorSource(
                    name="Reuters Business",
                    type="rss",
                    url="https://www.reutersagency.com/feed/?best-topics=business-finance",
                    keywords='["business","trade","economy","market"]',
                ),
            ]
            db.add_all(sources)

        # Seed notification settings if empty
        if db.query(NotificationSetting).count() == 0:
            notifs = [
                NotificationSetting(channel="web", is_enabled=True, config="{}"),
                NotificationSetting(channel="line", is_enabled=False, config='{"token":""}'),
                NotificationSetting(
                    channel="email",
                    is_enabled=False,
                    config='{"recipient":""}',
                ),
            ]
            db.add_all(notifs)

        db.commit()
    finally:
        db.close()
