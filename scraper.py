"""
scraper.py
----------
Orchestrates collecting accounting ("محاسب") job postings in Riyadh
("الرياض"), filtering for relevance, deduplicating against
seen_jobs.json, and pushing new postings to Telegram.

Two kinds of sources feed into this, controlled by config.SOURCES_ENABLED:
  - Direct website scraping (scrape_bayt / scrape_tanqeeb below) - off by
    default because Bayt.com sits behind Cloudflare, which blocks
    requests from data-center IPs (including GitHub Actions runners)
    regardless of headers.
  - email_alerts.read_alert_emails() - reads each site's own official
    job-alert emails from Gmail via IMAP. On by default; see
    email_alerts.py and the README for setup.

NOTE ON WEBSITE SELECTORS
-------------------------
If you ever re-enable "bayt" / "tanqeeb" (e.g. running from a home
network instead of GitHub Actions), note that public job boards change
their HTML periodically. Each field (card / title / company / location
/ snippet) has a short list of candidate CSS selectors tried in order.
If a source stops returning jobs:
  1. Set SCRAPER_DEBUG=1 and run once locally -> raw HTML for every
     fetched page is saved under debug_html/.
  2. Open that file, find the new class/tag names for job cards, and
     add them to the relevant *_SELECTORS list below.
"""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

import config
import telegram_bot
import utils

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# HTTP helpers (direct-website scrapers only)
# ---------------------------------------------------------------------------
def fetch(url: str, source_name: str = "") -> str | None:
    """GET a URL with retries; return response text, or None on failure."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                utils.save_debug_html(url, source_name, resp.text)
                return resp.text
            logger.warning(
                "%s: GET %s returned status %s (attempt %s/%s)",
                source_name, url, resp.status_code, attempt, config.MAX_RETRIES,
            )
        except requests.RequestException as exc:
            logger.warning(
                "%s: request to %s failed (attempt %s/%s): %s",
                source_name, url, attempt, config.MAX_RETRIES, exc,
            )
        time.sleep(config.REQUEST_DELAY * attempt)
    logger.error("%s: giving up on %s after %s attempts.", source_name, url, config.MAX_RETRIES)
    return None


def is_relevant(job: dict) -> bool:
    """Safety-net filter: keep only postings that mention an accounting
    term *and* Riyadh, in case a source includes sponsored or off-topic
    listings. Applied to every source, including email."""
    haystack = " ".join(str(job.get(f, "")) for f in ("title", "details", "location")).lower()
    keyword_hit = any(kw.lower() in haystack for kw in config.RELEVANCE_KEYWORDS)
    location_hit = any(loc in haystack for loc in config.RELEVANCE_LOCATIONS)
    return keyword_hit and location_hit


# ---------------------------------------------------------------------------
# Bayt.com (direct scrape - off by default, see config.SOURCES_ENABLED)
# ---------------------------------------------------------------------------
BAYT_CARD_SELECTORS = ["div[data-js-job]", "div.card-content", "li.has-pointer-d", "div.job-item"]
BAYT_TITLE_SELECTORS = ["h2.jb-title a", "h2 a", "a.job-title", "a[data-js-aid='jobTitle']"]
BAYT_COMPANY_SELECTORS = ["b.jb-company", "div.jb-company a", "a.employer", "span.company-name"]
BAYT_LOCATION_SELECTORS = ["div.jb-loc span", "span.jb-loc", "div.location", "span.location"]
BAYT_SNIPPET_SELECTORS = ["div.jb-descr", "p.jb-descr", "div.description", "p.job-description"]


def scrape_bayt(keyword: str = config.BAYT_KEYWORD, location_slug: str = config.BAYT_LOCATION_SLUG) -> list[dict]:
    """Scrape Bayt.com's Saudi Arabia job search for `keyword` in Riyadh."""
    slug = quote(f"{keyword}-jobs-in-{location_slug}")
    url = f"https://www.bayt.com/en/saudi-arabia/jobs/{slug}/"
    html = fetch(url, source_name="bayt")
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for sel in BAYT_CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            break

    jobs = []
    for card in cards:
        title_tag = utils.first_match(card, BAYT_TITLE_SELECTORS)
        title = utils.text_or_none(title_tag)
        if not title:
            continue  # can't parse this card at all, skip it rather than send junk

        href = title_tag.get("href")
        job_url = utils.absolute_url(url, href) if href else ""
        company = utils.text_or_none(utils.first_match(card, BAYT_COMPANY_SELECTORS)) or "Not specified"
        loc = utils.text_or_none(utils.first_match(card, BAYT_LOCATION_SELECTORS)) or "Riyadh"
        details = utils.text_or_none(utils.first_match(card, BAYT_SNIPPET_SELECTORS)) or ""

        jobs.append({
            "id": utils.make_job_id(job_url, title, company),
            "title": title,
            "company": company,
            "location": loc,
            "details": details,
            "contact": "Not available",
            "url": job_url,
            "source": "Bayt.com",
        })

    logger.info("bayt: parsed %s job card(s) from %s", len(jobs), url)
    return jobs


# ---------------------------------------------------------------------------
# Tanqeeb.com (direct scrape - off by default, see config.SOURCES_ENABLED)
# ---------------------------------------------------------------------------
TANQEEB_CARD_SELECTORS = ["div.job-item", "div.job-list-item", "li.job", "article.job"]
TANQEEB_TITLE_SELECTORS = ["h2 a", "a.job-title", "h3 a", "a.title"]
TANQEEB_COMPANY_SELECTORS = ["span.company", "div.company-name", "a.company"]
TANQEEB_LOCATION_SELECTORS = ["span.location", "div.job-location", "span.city"]
TANQEEB_SNIPPET_SELECTORS = ["p.description", "div.job-desc", "p.job-description"]


def scrape_tanqeeb(keyword: str = config.TANQEEB_KEYWORD, location: str = config.TANQEEB_LOCATION) -> list[dict]:
    """Scrape Tanqeeb.com's Saudi Arabia job search for `keyword` in Riyadh."""
    base = "https://sa.tanqeeb.com/jobs/saudi-arabia"
    url = f"{base}?keywords={quote(keyword)}&city={quote(location)}"
    html = fetch(url, source_name="tanqeeb")
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for sel in TANQEEB_CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            break

    jobs = []
    for card in cards:
        title_tag = utils.first_match(card, TANQEEB_TITLE_SELECTORS)
        title = utils.text_or_none(title_tag)
        if not title:
            continue

        href = title_tag.get("href")
        job_url = utils.absolute_url(url, href) if href else ""
        company = utils.text_or_none(utils.first_match(card, TANQEEB_COMPANY_SELECTORS)) or "Not specified"
        loc = utils.text_or_none(utils.first_match(card, TANQEEB_LOCATION_SELECTORS)) or location
        details = utils.text_or_none(utils.first_match(card, TANQEEB_SNIPPET_SELECTORS)) or ""

        jobs.append({
            "id": utils.make_job_id(job_url, title, company),
            "title": title,
            "company": company,
            "location": loc,
            "details": details,
            "contact": "Not available",
            "url": job_url,
            "source": "Tanqeeb.com",
        })

    logger.info("tanqeeb: parsed %s job card(s) from %s", len(jobs), url)
    return jobs


# ---------------------------------------------------------------------------
# Dedup state (seen_jobs.json) - shared across every source
# ---------------------------------------------------------------------------
def load_seen_ids(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return set(data.get("seen_ids", []))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s (%s); starting with an empty seen-set.", path, exc)
        return set()


def save_seen_ids(path: str, seen_ids: set[str]) -> None:
    trimmed = list(seen_ids)[-config.MAX_SEEN_JOBS:]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"seen_ids": trimmed}, fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def collect_all_jobs() -> list[dict]:
    jobs: list[dict] = []

    if config.SOURCES_ENABLED.get("bayt"):
        try:
            jobs.extend(scrape_bayt())
        except Exception:  # noqa: BLE001 - one source failing shouldn't kill the run
            logger.exception("bayt: scraping failed")
        time.sleep(config.REQUEST_DELAY)

    if config.SOURCES_ENABLED.get("tanqeeb"):
        try:
            jobs.extend(scrape_tanqeeb())
        except Exception:  # noqa: BLE001
            logger.exception("tanqeeb: scraping failed")

    if config.SOURCES_ENABLED.get("email"):
        try:
            import email_alerts
            jobs.extend(email_alerts.read_alert_emails())
        except Exception:  # noqa: BLE001
            logger.exception("email: reading alert emails failed")

    return jobs


def main() -> None:
    logger.info("Starting job scrape run.")
    all_jobs = collect_all_jobs()
    relevant_jobs = [j for j in all_jobs if is_relevant(j)]
    logger.info("%s job(s) collected, %s passed the relevance filter.", len(all_jobs), len(relevant_jobs))

    seen_ids = load_seen_ids(config.SEEN_JOBS_FILE)
    new_jobs = [j for j in relevant_jobs if j["id"] not in seen_ids]
    logger.info("%s new job(s) to send.", len(new_jobs))

    sent_ids = []
    for job in new_jobs:
        if telegram_bot.send_job_alert(job):
            sent_ids.append(job["id"])
        else:
            logger.warning("Failed to send alert for job: %s", job.get("title"))
        time.sleep(1)  # stay well under Telegram's rate limit

    if sent_ids:
        seen_ids.update(sent_ids)
        save_seen_ids(config.SEEN_JOBS_FILE, seen_ids)
        logger.info("Updated %s with %s new ID(s).", config.SEEN_JOBS_FILE, len(sent_ids))
    else:
        logger.info("Nothing new sent; %s left unchanged.", config.SEEN_JOBS_FILE)


if __name__ == "__main__":
    main()
