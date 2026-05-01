"""文章全文補抓器：對通過初篩的文章並行抓取 HTML，擷取主文寫回 article['content']。

雷達掃描原本只用 RSS 提供的 summary（通常是標題+前一兩句），導致排除關鍵字
與嚴重度評估都漏掉文章內文中的關鍵詞。本模組在初篩 dedup 後對少量候選文章
（5-30 篇）並行抓全文，讓後續排除/評分能看到完整內容。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# 既有 content 已超過此長度視為「scraper 已給足夠內文」，跳過抓取
_CONTENT_SKIP_LEN = 500
# 主文擷取後最少字數，低於此值視為失敗（多半是攔截頁/登入頁）
_MIN_BODY_LEN = 100


def _extract_main_text(html: str) -> Optional[str]:
    """從 HTML 抓主文文字。優先 <article>/<main>，退而求其次找最大 <div>。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript"]):
        tag.decompose()
    candidate = soup.find("article") or soup.find("main")
    if candidate:
        text = candidate.get_text(separator=" ", strip=True)
    else:
        divs = soup.find_all("div")
        if divs:
            best = max(divs, key=lambda d: len(d.get_text(strip=True)))
            text = best.get_text(separator=" ", strip=True)
        else:
            text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) < _MIN_BODY_LEN:
        return None
    return text


async def _fetch_one(client: httpx.AsyncClient, url: str, timeout: float) -> Optional[str]:
    try:
        r = await client.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        if r.status_code != 200:
            return None
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype.lower():
            return None
        return _extract_main_text(r.text)
    except Exception as e:
        logger.debug(f"fetch full body failed for {url}: {e}")
        return None


async def enrich_articles_with_full_body(
    articles: list[dict],
    concurrency: int = 5,
    timeout: float = 5.0,
) -> int:
    """對 articles 列表並行補抓全文，將擷取到的內文寫回 article['content']。

    跳過條件：
    - 沒有 source_url
    - 已標記 _body_fetched=True
    - 既有 content 長度 ≥ 500（scraper 已給足夠內文）
    - URL 仍是 news.google.com（未解碼 redirect，抓不到內文）

    抓取失敗時保留原 content（RSS summary 當 fallback），不會壞事。
    回傳實際成功補抓的篇數。
    """
    targets: list[tuple[int, str]] = []
    for idx, a in enumerate(articles):
        url = a.get("source_url") or a.get("url") or ""
        if not url:
            continue
        if a.get("_body_fetched"):
            continue
        if len(a.get("content", "") or "") >= _CONTENT_SKIP_LEN:
            continue
        if "news.google.com" in url:
            continue
        targets.append((idx, url))

    if not targets:
        return 0

    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:
        async def _job(idx: int, url: str) -> bool:
            async with sem:
                body = await _fetch_one(client, url, timeout)
                if body and len(body) > len(articles[idx].get("content", "") or ""):
                    articles[idx]["content"] = body
                    articles[idx]["_body_fetched"] = True
                    return True
            return False

        results = await asyncio.gather(
            *[_job(idx, url) for idx, url in targets],
            return_exceptions=True,
        )

    return sum(1 for r in results if r is True)
