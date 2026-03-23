import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routers import news_db, radar, search, settings
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


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


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
