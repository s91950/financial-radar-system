"""Research report RSS feed fetcher for IMF, BIS, Fed, ECB, BOJ, BOE.

Supports two fetch modes:
- RSS/Atom: standard feedparser parsing (BIS, Fed, BOE, BOJ)
- RePEc/IDEAS HTML scraping: for institutions whose RSS is broken (IMF, ECB, NBER)
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_date(entry) -> datetime | None:
    """Extract publication datetime from feed entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                pass
    # Try string fields
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return parsedate_to_datetime(val).replace(tzinfo=None)
            except Exception:
                pass
    return None


def _extract_pdf_url(entry) -> str:
    """Extract direct PDF URL from entry enclosures or link."""
    # Check enclosures (some feeds attach PDF directly)
    for enc in getattr(entry, "enclosures", []):
        url = enc.get("url", "") or enc.get("href", "")
        mime = enc.get("type", "") or enc.get("mime_type", "")
        if "pdf" in mime.lower() or url.lower().endswith(".pdf"):
            return url
    # Check if the main link is a PDF
    link = getattr(entry, "link", "") or ""
    if link.lower().endswith(".pdf"):
        return link
    # Check related links
    for rel in getattr(entry, "links", []):
        url = rel.get("href", "")
        mime = rel.get("type", "") or ""
        if "pdf" in mime.lower() or url.lower().endswith(".pdf"):
            return url
    return link  # Fall back to entry link


def _extract_authors(entry) -> list[str]:
    """Extract author names from feed entry."""
    authors = []
    # feedparser parses <author> and <dc:creator>
    for a in getattr(entry, "authors", []):
        name = a.get("name", "").strip()
        if name:
            authors.append(name)
    if not authors and hasattr(entry, "author") and entry.author:
        authors.append(entry.author.strip())
    return authors


def _extract_abstract(entry) -> str:
    """Extract abstract/summary from feed entry."""
    # Try summary_detail first (plain text preferred)
    detail = getattr(entry, "summary_detail", None)
    if detail:
        return detail.get("value", "").strip()
    summary = getattr(entry, "summary", "") or ""
    if summary:
        return summary.strip()
    # Fallback to content
    for c in getattr(entry, "content", []):
        text = c.get("value", "").strip()
        if text:
            return text[:2000]
    return ""


async def _fetch_repec_detail(client: httpx.AsyncClient, url: str) -> dict:
    """Fetch metadata from a single RePEc/IDEAS paper detail page."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        meta = {}
        for m in soup.select("meta[name]"):
            name = m.get("name", "").lower()
            content = m.get("content", "")
            if name == "citation_title":
                meta["title"] = content
            elif name == "title" and "title" not in meta:
                meta["title"] = content
            elif name == "citation_authors":
                meta["authors_str"] = content
            elif name == "author" and "authors_str" not in meta:
                meta["authors_str"] = content
            elif name == "citation_publication_date":
                meta["date"] = content  # prefer this over generic "date"
            elif name == "date" and "date" not in meta:
                meta["date"] = content
            elif name == "citation_abstract":
                meta["abstract"] = content
            elif name == "citation_abstract_html_url":
                meta.setdefault("source_url", content)
        # Find PDF download link (from linked DOI or direct)
        pdf_links = soup.select('a[href*=".pdf"]')
        if pdf_links:
            meta["pdf_url"] = pdf_links[0]["href"]
        return meta
    except Exception as e:
        logger.debug(f"RePEc detail fetch failed for {url}: {e}")
        return {}


async def _scrape_repec_listing(
    url: str, institution: str, hours_back: int = 72, max_papers: int = 30,
) -> list[dict]:
    """Scrape papers from a RePEc/IDEAS listing page.

    url: e.g. https://ideas.repec.org/s/ecb/ecbwps.html
    """
    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=_HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            mark_attempt(url, success=True)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Collect paper links from listing
            paper_items = []
            for li in soup.select("li"):
                link = li.select_one('a[href*="/p/"]')
                if not link:
                    continue
                href = link["href"]
                title = link.get_text(strip=True)
                # Skip sorting/navigation links
                if title in ("By citations", "By downloads") or len(title) < 5:
                    continue
                # Build full URL
                full_url = href if href.startswith("http") else f"https://ideas.repec.org{href}"
                paper_items.append({"title": title, "url": full_url})

            # Only fetch detail for the most recent N papers (listing is sorted newest-first)
            paper_items = paper_items[:max_papers]
            if not paper_items:
                return []

            # Fetch detail pages in parallel (batches of 10 to be polite)
            results = []
            for i in range(0, len(paper_items), 10):
                batch = paper_items[i : i + 10]
                details = await asyncio.gather(
                    *[_fetch_repec_detail(client, p["url"]) for p in batch],
                    return_exceptions=True,
                )
                for paper, detail in zip(batch, details):
                    if isinstance(detail, Exception) or not detail:
                        detail = {}
                    title = detail.get("title", paper["title"])
                    abstract = detail.get("abstract", "")
                    authors_str = detail.get("authors_str", "")
                    authors = [a.strip() for a in authors_str.replace(";", ",").split(",") if a.strip()] if authors_str else []
                    date_str = detail.get("date", "")
                    source_url = detail.get("source_url", paper["url"])
                    pdf_url = detail.get("pdf_url", source_url)

                    # Parse date and filter by hours_back
                    pub_dt = None
                    if date_str:
                        try:
                            # date_str can be "2026-02-02" or "2026/03"
                            clean = date_str.replace("/", "-")
                            if len(clean) <= 7:
                                clean += "-01"
                            pub_dt = datetime.fromisoformat(clean)
                        except Exception:
                            pass

                    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
                    if pub_dt and pub_dt < cutoff:
                        continue

                    results.append({
                        "title": title,
                        "abstract": abstract[:2000] if abstract else "",
                        "authors": json.dumps(authors, ensure_ascii=False),
                        "source": institution,
                        "source_url": source_url,
                        "pdf_url": pdf_url,
                        "publication_date": pub_dt.isoformat() if pub_dt else None,
                    })

            logger.info(f"RePEc scrape {institution}: fetched {len(results)} entries")
            return results
    except Exception as e:
        logger.warning(f"RePEc scrape failed ({institution}): {e}")
        mark_attempt(url, success=False, error=str(e))
        return []


def _is_repec_url(url: str) -> bool:
    """Check if a URL is a RePEc/IDEAS listing page."""
    return "ideas.repec.org" in url or "econpapers.repec.org" in url


async def fetch_research_feed(url: str, institution: str, hours_back: int = 72) -> list[dict]:
    """Fetch research reports from a single institutional feed.

    Automatically detects feed type:
    - RePEc/IDEAS URLs → HTML scraping
    - All other URLs → RSS/Atom parsing

    Returns list of dicts with keys: title, abstract, authors, source,
    source_url, pdf_url, publication_date.
    """
    # Route to scraper for RePEc/IDEAS URLs
    if _is_repec_url(url):
        return await _scrape_repec_listing(url, institution, hours_back)

    from backend.services.source_health import mark_attempt
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            verify=False,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.text
        mark_attempt(url, success=True)
    except Exception as e:
        logger.warning(f"Research feed fetch failed ({institution}): {e}")
        mark_attempt(url, success=False, error=str(e))
        return []

    try:
        feed = feedparser.parse(raw)
    except Exception as e:
        logger.warning(f"Research feed parse failed ({institution}): {e}")
        return []

    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    results = []

    for entry in feed.entries:
        title = (getattr(entry, "title", "") or "").strip()
        if not title:
            continue

        pub_dt = _parse_date(entry)
        # If no date or too old, skip
        if pub_dt and pub_dt < cutoff:
            continue

        results.append({
            "title": title,
            "abstract": _extract_abstract(entry),
            "authors": json.dumps(_extract_authors(entry), ensure_ascii=False),
            "source": institution,
            "source_url": getattr(entry, "link", "") or "",
            "pdf_url": _extract_pdf_url(entry),
            "publication_date": pub_dt.isoformat() if pub_dt else None,
        })

    logger.info(f"Research feed {institution}: fetched {len(results)} entries")
    return results


async def fetch_all_research_feeds(
    sources: list[dict],
    hours_back: int = 72,
) -> list[dict]:
    """Fetch multiple institutional feeds concurrently.

    sources: list of {name, url} dicts (from MonitorSource where type='research')
    """
    tasks = [
        fetch_research_feed(s["url"], s["name"], hours_back)
        for s in sources
    ]
    results_nested = await asyncio.gather(*tasks, return_exceptions=True)

    all_reports = []
    for s, result in zip(sources, results_nested):
        if isinstance(result, Exception):
            logger.error(f"Research feed error for {s['name']}: {result}")
        else:
            all_reports.extend(result)

    return all_reports
