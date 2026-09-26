"""
utils.py
--------
Small, source-agnostic helpers shared between the website scraper
(scraper.py) and the email-based alert reader (email_alerts.py): plain
text extraction from a BeautifulSoup tag, trying a list of candidate
CSS selectors in order, turning a possibly-relative URL into an
absolute one, a stable dedup ID, and the debug-HTML dump used by
SCRAPER_DEBUG=1.
"""

from __future__ import annotations

import hashlib
import logging
import os
from urllib.parse import urlsplit

import config

logger = logging.getLogger(__name__)


def text_or_none(tag) -> str | None:
    if tag is None:
        return None
    return " ".join(tag.get_text(separator=" ", strip=True).split()) or None


def first_match(container, selectors: list[str]):
    """Return the first element found trying each CSS selector in order."""
    for sel in selectors:
        found = container.select_one(sel)
        if found is not None:
            return found
    return None


def absolute_url(base: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if not href.startswith("/"):
        href = "/" + href
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}{href}"


def make_job_id(url: str, title: str, company: str) -> str:
    """Stable dedup ID: prefer the job URL, else hash of title+company."""
    basis = url or f"{title}|{company}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def save_debug_html(label: str, source_name: str, html: str) -> None:
    """Dump raw HTML to debug_html/ when SCRAPER_DEBUG=1, for fixing selectors."""
    if not config.DEBUG_SAVE_HTML:
        return
    os.makedirs(config.DEBUG_DIR, exist_ok=True)
    safe_name = hashlib.md5(label.encode("utf-8")).hexdigest()[:10]
    path = os.path.join(config.DEBUG_DIR, f"{source_name or 'page'}_{safe_name}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    logger.info("Saved debug HTML to %s", path)
