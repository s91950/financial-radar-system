"""APScheduler jobs for radar scanning and daily news collection."""

import asyncio
import json
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.database import (
    Alert,
    Article,
    MarketWatchItem,
    MonitorSource,
    NotificationSetting,
    SessionLocal,
    SignalCondition,
)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
_ws_manager = None


def start_scheduler(ws_manager):
    """Start the APScheduler with all jobs."""
    global _ws_manager
    _ws_manager = ws_manager

    from datetime import timedelta

    # First run after 30 seconds, then every N minutes
    first_run = datetime.utcnow() + timedelta(seconds=30)

    # Radar scan every N minutes
    scheduler.add_job(
        radar_scan,
        "interval",
        minutes=settings.RADAR_INTERVAL_MINUTES,
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

    # Market data refresh every hour (or configured interval)
    scheduler.add_job(
        market_check,
        "interval",
        minutes=settings.MARKET_CHECK_INTERVAL_MINUTES,
        id="market_check",
        name="市場指標檢查",
        next_run_time=first_run,
    )

    scheduler.start()
    logger.info("Scheduler started with radar and daily news jobs")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


async def radar_scan():
    """Main radar scan job - checks all sources for new signals.

    Flow: Fetch news → match position exposure → create alert (no AI) → notify
    """
    from backend.services import rss_feed
    from backend.services.google_news import search_google_news
    from backend.services.exposure import format_exposure_summary, match_positions_to_news
    from backend.services.google_sheets import get_positions

    logger.info("Running radar scan...")
    db = SessionLocal()

    try:
        # 1. Fetch from active RSS sources
        sources = db.query(MonitorSource).filter(
            MonitorSource.is_active == True,
            MonitorSource.type == "rss",
        ).all()

        feeds = [
            {
                "name": s.name,
                "url": s.url,
                "keywords": json.loads(s.keywords) if s.keywords else [],
            }
            for s in sources
        ]

        new_articles = []
        if feeds:
            rss_results = await rss_feed.fetch_multiple_feeds(feeds, hours_back=1)
            for article_data in rss_results:
                url = article_data.get("source_url", "")
                if url and not db.query(Article).filter(Article.source_url == url).first():
                    new_articles.append(article_data)

        # 2. Fetch latest headlines via Google News RSS
        for topic in ["金融", "股市", "經濟"]:
            headlines = await search_google_news(query=topic, hours_back=1, max_results=5)
            for article_data in headlines:
                url = article_data.get("source_url", "")
                if url and not db.query(Article).filter(Article.source_url == url).first():
                    new_articles.append(article_data)

        if not new_articles:
            logger.info("Radar scan: no new articles found")
            return

        # 3. Save new articles
        for data in new_articles:
            article = Article(
                title=data.get("title", ""),
                content=data.get("content", ""),
                source=data.get("source", ""),
                source_url=data.get("source_url", ""),
                published_at=_parse_datetime(data.get("published_at")),
                category=data.get("category", "radar"),
            )
            db.add(article)

        # 4. Match position exposure (from Google Sheets)
        positions = await get_positions()
        matched = match_positions_to_news(positions, new_articles) if positions else []
        exposure_summary = format_exposure_summary(matched) if matched else ""

        # Collect source URLs
        source_urls = [a.get("source_url", "") for a in new_articles if a.get("source_url")]

        # 5. Create alert (NO AI analysis - user triggers on demand)
        alert = Alert(
            type="news",
            title=f"偵測到 {len(new_articles)} 則新資訊",
            content="\n".join(
                f"[{a.get('source', '')}] {a.get('title', '')}"
                for a in new_articles[:10]
            ),
            analysis=None,  # User triggers AI analysis on demand
            severity=_assess_severity(new_articles),
            source="Radar Scan",
            exposure_summary=exposure_summary or None,
            source_urls=json.dumps(source_urls[:5]) if source_urls else None,
        )
        db.add(alert)
        db.commit()

        # 6. Broadcast via WebSocket
        if _ws_manager:
            await _ws_manager.broadcast({
                "type": "radar_alert",
                "data": {
                    "id": alert.id,
                    "title": alert.title,
                    "severity": alert.severity,
                    "content": alert.content[:300],
                    "exposure_summary": exposure_summary,
                    "source_urls": source_urls[:5],
                    "created_at": datetime.utcnow().isoformat(),
                },
            })

        # 7. Send external notifications (LINE/Email) with exposure info
        alert_dict_extra = {
            "title": alert.title,
            "content": alert.content,
            "analysis": alert.analysis,
            "severity": alert.severity,
            "source": alert.source,
            "source_url": alert.source_url,
            "type": alert.type,
            "exposure_summary": exposure_summary,
            "source_urls": source_urls[:5],
        }
        await _send_notifications_with_data(alert_dict_extra, db)

        logger.info(f"Radar scan complete: {len(new_articles)} new articles, {len(matched)} positions affected")

    except Exception as e:
        logger.error(f"Radar scan error: {e}")
        db.rollback()
    finally:
        db.close()


async def market_check():
    """Check market indicators using signal conditions and trigger alerts on state changes."""
    from backend.services import claude_ai, market_data

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

                # AI analysis only if API key is configured
                analysis = None
                if settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY != "your_anthropic_api_key_here":
                    analysis = await claude_ai.analyze_market_signal(
                        symbol=item.symbol,
                        name=item.name,
                        value=price,
                        change_percent=change_pct,
                        threshold_type=trigger_msg,
                    )

                alert = Alert(
                    type="market",
                    title=f"📊 {item.name} — {trigger_msg}",
                    content=f"{item.name} ({item.symbol}) 當前值: {price} ({change_pct:+.2f}%)",
                    analysis=analysis,
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
                            "analysis": analysis[:300],
                        },
                    })

                await _send_notifications(alert, db)

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
            }
            for s in sources
        ]
        if feeds:
            rss_results = await rss_feed.fetch_multiple_feeds(feeds, hours_back=24)
            articles_data.extend(rss_results)

        # Save with dedup
        saved = 0
        for data in articles_data:
            url = data.get("source_url", "")
            if url and db.query(Article).filter(Article.source_url == url).first():
                continue
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


async def _send_notifications(alert, db):
    """Send notifications through enabled channels (from Alert ORM object)."""
    alert_dict = {
        "title": alert.title,
        "content": alert.content,
        "analysis": alert.analysis,
        "severity": alert.severity,
        "source": alert.source,
        "source_url": alert.source_url,
        "type": alert.type,
    }
    await _send_notifications_with_data(alert_dict, db)


async def _send_notifications_with_data(alert_dict: dict, db):
    """Send notifications through enabled channels (from dict with extra fields)."""
    from backend.services.notification import (
        format_alert_email,
        format_alert_message,
        send_email,
        send_line_notify,
    )

    settings_list = db.query(NotificationSetting).filter(
        NotificationSetting.is_enabled == True
    ).all()

    for setting in settings_list:
        try:
            if setting.channel == "line":
                config = json.loads(setting.config) if setting.config else {}
                token = config.get("token")
                msg = format_alert_message(alert_dict)
                await send_line_notify(msg, token=token)

            elif setting.channel == "email":
                config = json.loads(setting.config) if setting.config else {}
                recipient = config.get("recipient")
                body = format_alert_email(alert_dict)
                await send_email(
                    subject=f"[金融偵測] {alert_dict.get('title', '')}",
                    body=body,
                    recipient=recipient,
                )
        except Exception as e:
            logger.error(f"Notification send error ({setting.channel}): {e}")


def _assess_severity(articles: list[dict]) -> str:
    """Simple heuristic to assess alert severity."""
    high_keywords = ["崩盤", "暴跌", "危機", "crash", "crisis", "emergency", "戰爭", "制裁"]
    medium_keywords = ["升息", "降息", "衰退", "recession", "inflation", "通膨"]

    text = " ".join(a.get("title", "") + " " + a.get("content", "")[:200] for a in articles).lower()

    if any(kw in text for kw in high_keywords):
        return "critical"
    if any(kw in text for kw in medium_keywords):
        return "high"
    if len(articles) >= 5:
        return "medium"
    return "low"


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
