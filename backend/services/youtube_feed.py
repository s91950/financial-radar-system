"""YouTube channel RSS feed fetcher. No API key required.

YouTube provides public Atom feeds per channel:
  https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
Returns the 15 most recent videos.
"""

import logging
import re
from calendar import timegm
from datetime import datetime
from typing import Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)

_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _parse_published(entry) -> Optional[datetime]:
    """Parse published date from RSS entry as UTC datetime.
    feedparser returns published_parsed as a UTC time_struct;
    must use timegm (not mktime) to avoid treating it as local time."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime.utcfromtimestamp(timegm(entry.published_parsed))
        except Exception:
            pass
    return None


async def fetch_channel_videos(channel_id: str) -> list[dict]:
    """Fetch recent videos for a YouTube channel via public RSS feed."""
    url = _FEED_URL.format(channel_id=channel_id)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            feed_text = resp.text
    except Exception as e:
        logger.error(f"YouTube RSS fetch error for {channel_id}: {e}")
        return []

    try:
        feed = feedparser.parse(feed_text)
    except Exception as e:
        logger.error(f"feedparser error for {channel_id}: {e}")
        return []

    videos = []
    for entry in feed.entries:
        # Extract video ID
        video_id = getattr(entry, "yt_videoid", None)
        if not video_id:
            eid = getattr(entry, "id", "") or ""
            m = re.search(r"watch\?v=([A-Za-z0-9_-]{11})", eid)
            if m:
                video_id = m.group(1)
        if not video_id:
            continue

        # Thumbnail: prefer media_thumbnail, fallback to standard URL
        thumbnail = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            thumbnail = entry.media_thumbnail[0].get("url", thumbnail)

        # Description from media:group > media:description or summary
        description = ""
        if hasattr(entry, "media_description"):
            description = entry.media_description or ""
        elif hasattr(entry, "summary"):
            description = entry.summary or ""
        # Strip HTML tags
        description = re.sub(r"<[^>]+>", "", description).strip()[:500]

        videos.append({
            "video_id": video_id,
            "title": getattr(entry, "title", ""),
            "description": description,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_url": thumbnail,
            "published_at": _parse_published(entry),
        })

    return videos


async def resolve_channel_id(user_input: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve user input to (channel_id, channel_name).

    Accepts:
    - Channel ID directly (starts with UC…)
    - URL: https://www.youtube.com/channel/UCxxxxxx
    - URL: https://www.youtube.com/@handle  or  @handle
    - URL: https://www.youtube.com/c/channelname (legacy)
    """
    user_input = user_input.strip()

    # Already a channel ID
    if re.match(r"^UC[A-Za-z0-9_-]{22}$", user_input):
        return user_input, None

    # Extract from /channel/UCxxxxxx URL
    m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", user_input)
    if m:
        return m.group(1), None

    # Handle @handle — scrape HTML to find channelId
    handle = None
    if user_input.startswith("@"):
        handle = user_input
    elif "/@" in user_input:
        handle = "@" + user_input.split("/@")[-1].split("/")[0].split("?")[0]
    elif "/c/" in user_input:
        slug = user_input.split("/c/")[-1].split("/")[0]
        handle = slug  # use as path

    if handle:
        try:
            page_url = f"https://www.youtube.com/{handle}" if not handle.startswith("http") else handle
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(page_url, headers={"User-Agent": "Mozilla/5.0"})
                text = resp.text
            for pattern in [
                r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
                r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
                r'canonical.*?/channel/(UC[A-Za-z0-9_-]{22})',
            ]:
                mm = re.search(pattern, text)
                if mm:
                    return mm.group(1), None
        except Exception as e:
            logger.error(f"Failed to resolve YouTube handle {handle}: {e}")

    return None, None


async def get_channel_info(channel_id: str) -> dict:
    """Get channel name from its RSS feed."""
    url = _FEED_URL.format(channel_id=channel_id)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        name = feed.feed.get("title") or channel_id
        return {"name": name}
    except Exception as e:
        logger.error(f"YouTube channel info error for {channel_id}: {e}")
        return {"name": channel_id}
