"""來源健康狀態追蹤。

scraper 在每次嘗試抓取後呼叫 mark_attempt() 記錄結果。
DB 更新欄位：
  last_attempt_at — 最後一次嘗試時間（成功或失敗）
  last_success_at — 最後一次 HTTP 200 成功時間（成功時更新）
  last_error      — 最後一次失敗訊息（成功時清空，失敗時設值）

故障安全：DB 寫入失敗只記 log，不向上拋例外，不影響掃描流程。
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import update

from backend.database import MonitorSource, SessionLocal

logger = logging.getLogger(__name__)


def mark_attempt(url: str, success: bool, error: Optional[str] = None) -> None:
    """更新 MonitorSource 健康欄位。Best-effort，永不拋例外。

    url: MonitorSource.url（精確比對）。若資料庫沒有對應列，靜默略過。
    success: True = HTTP 抓取成功；False = 失敗
    error: 失敗時的錯誤訊息（自動截斷至 500 字）
    """
    try:
        now = datetime.utcnow()
        values = {"last_attempt_at": now}
        if success:
            values["last_success_at"] = now
            values["last_error"] = None
        else:
            values["last_error"] = (str(error) if error else "unknown error")[:500]

        with SessionLocal() as db:
            db.execute(
                update(MonitorSource)
                .where(MonitorSource.url == url)
                .values(**values)
            )
            db.commit()
    except Exception as e:
        logger.warning(f"mark_attempt failed for {url}: {e}")
