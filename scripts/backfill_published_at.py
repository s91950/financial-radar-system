"""一次性 backfill：對 published_at 為空的文章補抓 HTML 並擷取發布時間。

在 VM 上執行：
    cd /opt/financial-radar && sudo -u s9195000409898 python scripts/backfill_published_at.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

# 加入專案根目錄到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, Article  # noqa: E402
from backend.services.article_fetcher import enrich_articles_with_full_body  # noqa: E402
from backend.scheduler.jobs import _parse_datetime  # noqa: E402


async def main():
    db = SessionLocal()
    try:
        rows = db.query(Article).filter(
            (Article.published_at.is_(None)) | (Article.published_at == "")
        ).all()
        print(f"找到 {len(rows)} 篇文章缺發布時間")
        if not rows:
            return

        articles = [
            {"id": r.id, "source_url": r.source_url, "content": r.content or "", "published_at": None}
            for r in rows if r.source_url
        ]
        print(f"扣掉無 URL 後實際補抓：{len(articles)} 篇")

        enriched = await enrich_articles_with_full_body(articles, concurrency=5, timeout=8.0)
        print(f"補抓成功（內文或時間至少更新一項）：{enriched} 篇")

        updated = 0
        for a in articles:
            pa = a.get("published_at")
            if not pa:
                continue
            dt = _parse_datetime(pa)
            if not dt:
                continue
            row = db.query(Article).filter(Article.id == a["id"]).first()
            if row and not row.published_at:
                row.published_at = dt
                updated += 1
        db.commit()
        print(f"published_at 回填完成：{updated} 篇")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
