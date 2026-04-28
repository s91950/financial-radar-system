import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Set

from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routers import line_webhook, news_db, radar, research, search, settings, topics, youtube
from backend.scheduler.jobs import start_scheduler, stop_scheduler


# --- WebSocket Connection Manager ---

class ConnectionManager:
    """Manages active WebSocket connections for real-time notifications."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead = set()
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                dead.add(conn)
        self.active_connections -= dead


manager = ConnectionManager()


# --- App Lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    start_scheduler(manager)
    yield
    # Shutdown
    stop_scheduler()


# --- FastAPI App ---

app = FastAPI(
    title="金融即時偵測系統",
    description="即時偵測雷達、主題搜尋、新聞資料庫",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(radar.router, prefix="/api/radar", tags=["雷達"])
app.include_router(search.router, prefix="/api/search", tags=["搜尋"])
app.include_router(news_db.router, prefix="/api/news", tags=["新聞資料庫"])
app.include_router(settings.router, prefix="/api/settings", tags=["設定"])
app.include_router(topics.router, prefix="/api/topics", tags=["主題追蹤"])
app.include_router(research.router, prefix="/api/research", tags=["研究報告"])
app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube 頻道"])
app.include_router(line_webhook.router, prefix="/api", tags=["LINE Webhook"])

from backend.routers import feedback
app.include_router(feedback.router, prefix="/api/feedback", tags=["意見回饋"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/api/utils/resolve-url")
async def resolve_url(url: str):
    """Follow HTTP redirects and return the final article URL.

    Used by the frontend copy function to convert RSS redirect URLs
    (e.g. feeds.reuters.com, feedburner) into readable article URLs
    that AI tools like Gemini can fetch directly.
    """
    import httpx
    if not url or not url.startswith("http"):
        return {"url": url, "resolved": False}
    try:
        async with httpx.AsyncClient(timeout=8, verify=False, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                final = str(resp.url)
            if final.startswith("http") and final != url:
                return {"url": final, "resolved": True}
    except Exception:
        pass
    return {"url": url, "resolved": False}


@app.post("/api/utils/resolve-stored-urls")
async def resolve_stored_urls(background_tasks: BackgroundTasks):
    """One-time background job to resolve all Google News redirect URLs
    stored in alerts (source_urls field) and articles (source_url field).
    """
    background_tasks.add_task(_resolve_stored_urls_task)
    return {"message": "URL 解析任務已啟動，正在背景執行"}


async def _resolve_stored_urls_task():
    """Resolve news.google.com redirect URLs stored in DB to actual article URLs."""
    import asyncio
    import json
    import httpx
    from backend.database import Alert, Article, SessionLocal

    logger_main = __import__("logging").getLogger(__name__)

    async def resolve_one(url: str, client: httpx.AsyncClient) -> str:
        if not url or "news.google.com" not in url:
            return url
        try:
            async with client.stream("GET", url, follow_redirects=True, timeout=8) as resp:
                final = str(resp.url)
            if final.startswith("http") and final != url:
                return final
        except Exception:
            pass
        return url

    db = SessionLocal()
    updated = 0
    try:
        async with httpx.AsyncClient(
            timeout=10, verify=False, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            # Resolve alert source_urls (JSON array field)
            alerts = db.query(Alert).filter(Alert.source_urls.isnot(None)).all()
            for alert in alerts:
                try:
                    urls = json.loads(alert.source_urls)
                except Exception:
                    continue
                if not any("news.google.com" in u for u in urls):
                    continue
                resolved = await asyncio.gather(*[resolve_one(u, client) for u in urls])
                alert.source_urls = json.dumps(list(resolved))
                updated += 1

            # Resolve article source_url (single string field)
            articles = db.query(Article).filter(Article.source_url.contains("news.google.com")).all()
            for article in articles:
                resolved = await resolve_one(article.source_url, client)
                if resolved != article.source_url:
                    article.source_url = resolved
                    updated += 1

        db.commit()
        logger_main.info(f"resolve_stored_urls: updated {updated} records")
    except Exception as e:
        logger_main.error(f"resolve_stored_urls error: {e}")
        db.rollback()
    finally:
        db.close()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Echo back acknowledgement
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
