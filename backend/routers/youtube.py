"""Router for YouTube channel monitoring."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import YoutubeChannel, YoutubeVideo, get_db

router = APIRouter()


class ChannelCreate(BaseModel):
    url: str                          # channel ID, full URL, or @handle
    check_interval_minutes: int = 30


class ChannelUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    check_interval_minutes: int | None = None


# ---------------------------------------------------------------------------
# Channels CRUD
# ---------------------------------------------------------------------------

@router.get("/channels")
async def get_channels(db: Session = Depends(get_db)):
    """List all monitored YouTube channels with new-video counts."""
    channels = db.query(YoutubeChannel).order_by(YoutubeChannel.created_at).all()
    return [_channel_dict(c, db) for c in channels]


@router.post("/channels")
async def add_channel(req: ChannelCreate, db: Session = Depends(get_db)):
    """Add a new YouTube channel to monitor."""
    from backend.services.youtube_feed import fetch_channel_videos, get_channel_info, resolve_channel_id

    channel_id, _ = await resolve_channel_id(req.url)
    if not channel_id:
        return {"error": "無法解析頻道 ID，請輸入有效的頻道 ID（UCxxxxxx）、頻道網址或 @handle"}

    if db.query(YoutubeChannel).filter(YoutubeChannel.channel_id == channel_id).first():
        return {"error": f"頻道 {channel_id} 已在監控清單中"}

    info = await get_channel_info(channel_id)
    channel = YoutubeChannel(
        channel_id=channel_id,
        name=info.get("name") or channel_id,
        url=req.url,
        check_interval_minutes=max(5, req.check_interval_minutes),
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)

    # Seed initial videos (mark is_new=False — not "new" on first load)
    videos = await fetch_channel_videos(channel_id)
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
                is_new=False,
            ))
    channel.last_checked_at = datetime.utcnow()
    db.commit()
    db.refresh(channel)
    return _channel_dict(channel, db)


@router.put("/channels/{channel_id}")
async def update_channel(channel_id: int, req: ChannelUpdate, db: Session = Depends(get_db)):
    """Update channel name, active state, or check interval."""
    channel = db.query(YoutubeChannel).filter(YoutubeChannel.id == channel_id).first()
    if not channel:
        return {"error": "找不到此頻道"}
    if req.name is not None:
        channel.name = req.name
    if req.is_active is not None:
        channel.is_active = req.is_active
    if req.check_interval_minutes is not None:
        channel.check_interval_minutes = max(5, req.check_interval_minutes)
    db.commit()
    return _channel_dict(channel, db)


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    """Delete a channel and all its videos."""
    channel = db.query(YoutubeChannel).filter(YoutubeChannel.id == channel_id).first()
    if not channel:
        return {"error": "找不到此頻道"}
    db.delete(channel)
    db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

@router.get("/videos")
async def get_videos(
    channel_id: int | None = None,
    new_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List videos, optionally filtered by channel or new-only."""
    q = db.query(YoutubeVideo)
    if channel_id:
        q = q.filter(YoutubeVideo.channel_db_id == channel_id)
    if new_only:
        q = q.filter(YoutubeVideo.is_new == True)
    videos = q.order_by(YoutubeVideo.published_at.desc()).limit(limit).all()
    return [_video_dict(v) for v in videos]


@router.get("/new-count")
async def get_new_count(db: Session = Depends(get_db)):
    """Return number of unseen (new) videos."""
    count = db.query(YoutubeVideo).filter(YoutubeVideo.is_new == True).count()
    return {"count": count}


@router.put("/videos/{video_id}/seen")
async def mark_seen(video_id: int, db: Session = Depends(get_db)):
    """Mark a single video as seen."""
    video = db.query(YoutubeVideo).filter(YoutubeVideo.id == video_id).first()
    if not video:
        return {"error": "找不到此影片"}
    video.is_new = False
    db.commit()
    return {"success": True}


@router.put("/videos/mark-all-seen")
async def mark_all_seen(channel_id: int | None = None, db: Session = Depends(get_db)):
    """Mark all (or all in a channel) videos as seen."""
    q = db.query(YoutubeVideo).filter(YoutubeVideo.is_new == True)
    if channel_id:
        q = q.filter(YoutubeVideo.channel_db_id == channel_id)
    q.update({"is_new": False}, synchronize_session=False)
    db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Manual check
# ---------------------------------------------------------------------------

@router.post("/channels/{channel_id}/check")
async def check_channel(channel_id: int, db: Session = Depends(get_db)):
    """Manually check a single channel for new videos."""
    channel = db.query(YoutubeChannel).filter(YoutubeChannel.id == channel_id).first()
    if not channel:
        return {"error": "找不到此頻道"}
    new_count = await _fetch_and_save(channel, db, mark_new=True)
    return {"new_videos": new_count, "channel": channel.name}


@router.post("/check-all")
async def check_all(db: Session = Depends(get_db)):
    """Check all active channels for new videos."""
    channels = db.query(YoutubeChannel).filter(YoutubeChannel.is_active == True).all()
    results = []
    for channel in channels:
        new_count = await _fetch_and_save(channel, db, mark_new=True)
        results.append({"channel": channel.name, "new_videos": new_count})
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_and_save(channel: YoutubeChannel, db: Session, mark_new: bool) -> int:
    """Fetch RSS for a channel, save new videos, return count of new items."""
    from backend.services.youtube_feed import fetch_channel_videos

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
                is_new=mark_new,
            ))
            new_count += 1
    channel.last_checked_at = datetime.utcnow()
    db.commit()
    return new_count


def _channel_dict(channel: YoutubeChannel, db: Session) -> dict:
    new_count = db.query(YoutubeVideo).filter(
        YoutubeVideo.channel_db_id == channel.id,
        YoutubeVideo.is_new == True,
    ).count()
    return {
        "id": channel.id,
        "channel_id": channel.channel_id,
        "name": channel.name,
        "url": channel.url,
        "thumbnail_url": channel.thumbnail_url,
        "is_active": channel.is_active,
        "check_interval_minutes": channel.check_interval_minutes,
        "last_checked_at": channel.last_checked_at.isoformat() if channel.last_checked_at else None,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
        "new_video_count": new_count,
    }


def _video_dict(video: YoutubeVideo) -> dict:
    return {
        "id": video.id,
        "video_id": video.video_id,
        "channel_db_id": video.channel_db_id,
        "channel_name": video.channel.name if video.channel else None,
        "title": video.title,
        "description": video.description,
        "url": video.url,
        "thumbnail_url": video.thumbnail_url,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "fetched_at": video.fetched_at.isoformat() if video.fetched_at else None,
        "is_new": video.is_new,
    }
