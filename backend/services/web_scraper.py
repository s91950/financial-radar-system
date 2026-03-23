"""Web scraper for custom website monitoring."""

import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def scrape_page(url: str, selector: str | None = None) -> dict:
    """Scrape a web page and extract text content.

    Args:
        url: Target URL
        selector: CSS selector to extract specific content (optional)

    Returns:
        {"title": str, "content": str, "source_url": str}
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        if selector:
            elements = soup.select(selector)
            content = "\n".join(el.get_text(strip=True) for el in elements)
        else:
            # Try common article selectors
            article = (
                soup.find("article")
                or soup.find("main")
                or soup.find(class_=lambda c: c and "content" in str(c).lower())
            )
            if article:
                content = article.get_text(separator="\n", strip=True)
            else:
                content = soup.get_text(separator="\n", strip=True)

        # Limit content length
        content = content[:5000] if len(content) > 5000 else content

        return {
            "title": title,
            "content": content,
            "source": _extract_domain(url),
            "source_url": url,
            "category": "scraped",
        }
    except Exception as e:
        logger.error(f"Scrape error ({url}): {e}")
        return {"title": "", "content": "", "source_url": url, "error": str(e)}


async def scrape_multiple(targets: list[dict]) -> list[dict]:
    """Scrape multiple pages.

    targets: list of {"url": str, "selector": str | None}
    """
    results = []
    for target in targets:
        result = await scrape_page(target["url"], target.get("selector"))
        if result.get("content"):
            results.append(result)
    return results


def _extract_domain(url: str) -> str:
    """Extract domain name from URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")
