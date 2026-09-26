"""
email_alerts.py
----------------
Reads Bayt.com / Tanqeeb.com job-alert emails from a Gmail inbox over
IMAP, extracts job postings out of them, and returns them in the same
shape scraper.py's website scrapers use (title/company/location/
details/contact/url/source) - so the rest of the pipeline (relevance
filter, dedup, Telegram) needs no changes at all.

WHY EMAIL INSTEAD OF SCRAPING THE WEBSITES DIRECTLY
----------------------------------------------------
Bayt.com sits behind Cloudflare, which blocks requests coming from
well-known data-center IP ranges (including GitHub Actions runners)
regardless of headers. Signing up for each site's own "Job Alert"
email feature sidesteps that entirely: the site does the search and
match itself and emails the result, and this script just reads that
inbox - no scraping of a protected page involved.

ONE-TIME SETUP (done by the mailbox owner, not by this script)
----------------------------------------------------------------
  1. On Bayt.com and Tanqeeb.com, search "Accountant"/"محاسب" jobs in
     Riyadh and turn on each site's built-in email job alert, pointed
     at the Gmail address this script will read.
  2. Turn on 2-Step Verification on that Google account, then create
     an "App Password" at https://myaccount.google.com/apppasswords .
     This is a separate 16-character code scoped to just this
     integration - NOT the normal account password - and can be
     revoked any time without touching anything else on the account.
  3. Store GMAIL_ADDRESS and GMAIL_APP_PASSWORD as GitHub Actions
     secrets (same place as the Telegram secrets). Never put them in
     code or paste them into a chat.

WHAT THIS SCRIPT ACTUALLY DOES TO THE MAILBOX
------------------------------------------------
Read-only except for one thing: after it successfully parses an
unread alert email, it flags that single email as read (\\Seen) so it
isn't processed again next run. It never deletes, sends, labels, or
touches any other mail.

NOTE ON PARSING
-----------------
The exact HTML inside a Bayt/Tanqeeb alert email isn't something this
environment can inspect live, so parsing tries a few candidate card
patterns first, and if none match, falls back to treating any link
that looks like a job posting as one job. If it stops finding jobs
inside emails that clearly contain them:
  1. Set SCRAPER_DEBUG=1 and run once -> the raw HTML of every
     processed email is saved under debug_html/.
  2. Open one, see how job entries are actually laid out, and add the
     new selector to CARD_SELECTORS / TITLE_SELECTORS / etc. below (or
     adjust JOB_LINK_HINT if the fallback needs a wider net).
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import re
from email.header import decode_header
from email.message import Message

from bs4 import BeautifulSoup

import config
import utils

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Candidate selectors for a single job entry ("card") inside an alert
# email's HTML body. Tried in order; first one that matches anything wins.
CARD_SELECTORS = ["table.job-row", "div.job-item", "tr.job", "div.job-card", "li.job"]
TITLE_SELECTORS = ["a.job-title", "h2 a", "h3 a", "a[href*='/jobs/']", "a"]
COMPANY_SELECTORS = ["span.company", "td.company", "div.company"]
LOCATION_SELECTORS = ["span.location", "td.location", "div.location"]

# Used by the link-based fallback: any <a href> matching this looks like a
# job posting link rather than a "manage my alerts" / unsubscribe link.
JOB_LINK_HINT = re.compile(r"/jobs?/|job[-_]?id=|jobid=", re.IGNORECASE)
GENERIC_LINK_TEXTS = {"here", "view", "click here", "apply", "apply now", "details", "view job", "read more", "see more"}


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="ignore")
        else:
            decoded += text
    return decoded


def _connect() -> imaplib.IMAP4_SSL | None:
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        logger.error("GMAIL_ADDRESS / GMAIL_APP_PASSWORD are not set; skipping email check.")
        return None
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        return imap
    except imaplib.IMAP4.error as exc:
        logger.error("IMAP login failed: %s", exc)
        return None


def _search_unseen_from(imap: imaplib.IMAP4_SSL, sender_hints: list[str]) -> list[bytes]:
    """Return message IDs of unseen mail whose From header contains any hint."""
    ids: list[bytes] = []
    imap.select("INBOX")
    for hint in sender_hints:
        typ, data = imap.search(None, f'(UNSEEN HEADER FROM "{hint}")')
        if typ == "OK" and data and data[0]:
            ids.extend(data[0].split())
    return list(dict.fromkeys(ids))  # de-dupe while keeping order


def _get_html_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="ignore")
                except Exception:  # noqa: BLE001
                    continue
        for part in msg.walk():  # fall back to plain text if no HTML part
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="ignore")
                except Exception:  # noqa: BLE001
                    continue
        return ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return msg.get_payload(decode=True).decode(charset, errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


def _extract_via_cards(soup: BeautifulSoup, source_name: str) -> list[dict]:
    cards = []
    for sel in CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            break

    jobs = []
    for card in cards:
        title_tag = utils.first_match(card, TITLE_SELECTORS)
        title = utils.text_or_none(title_tag)
        if not title:
            continue
        href = title_tag.get("href") if title_tag else ""
        company = utils.text_or_none(utils.first_match(card, COMPANY_SELECTORS)) or "Not specified"
        loc = utils.text_or_none(utils.first_match(card, LOCATION_SELECTORS)) or "Riyadh"

        jobs.append({
            "id": utils.make_job_id(href, title, company),
            "title": title,
            "company": company,
            "location": loc,
            "details": "",
            "contact": "Not available",
            "url": href or "",
            "source": source_name,
        })
    return jobs


def _extract_via_link_fallback(soup: BeautifulSoup, source_name: str) -> list[dict]:
    """Last resort: treat every job-looking link as one job, using its
    visible text as the title (preferring the longest, least generic
    text seen for that link). Used only if the card-based parse above
    found nothing, so a template change doesn't mean zero jobs forever."""
    best_title_by_href: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not JOB_LINK_HINT.search(href):
            continue
        text = utils.text_or_none(a)
        if not text:
            continue
        current = best_title_by_href.get(href)
        if current is None:
            best_title_by_href[href] = text
        elif text.lower() not in GENERIC_LINK_TEXTS and (
            current.lower() in GENERIC_LINK_TEXTS or len(text) > len(current)
        ):
            best_title_by_href[href] = text

    jobs = []
    for href, title in best_title_by_href.items():
        jobs.append({
            "id": utils.make_job_id(href, title, ""),
            "title": title,
            "company": "Not specified",
            "location": "Riyadh",
            "details": "",
            "contact": "Not available",
            "url": href,
            "source": source_name,
        })
    return jobs


def _parse_alert_email(raw_bytes: bytes, source_name: str) -> list[dict]:
    msg = email_lib.message_from_bytes(raw_bytes)
    html = _get_html_body(msg)
    if not html:
        return []

    subject = _decode_header_value(msg.get("Subject", "")) or "email"
    utils.save_debug_html(subject, f"email_{source_name.split('.')[0].lower()}", html)

    soup = BeautifulSoup(html, "html.parser")
    jobs = _extract_via_cards(soup, source_name)
    if not jobs:
        jobs = _extract_via_link_fallback(soup, source_name)
    return jobs


def read_alert_emails() -> list[dict]:
    """Connect to Gmail, pull unread Bayt/Tanqeeb alert emails, return jobs."""
    imap = _connect()
    if imap is None:
        return []

    all_jobs: list[dict] = []
    try:
        combined_hints = config.BAYT_SENDER_HINTS + config.TANQEEB_SENDER_HINTS
        msg_ids = _search_unseen_from(imap, combined_hints)
        logger.info("email: found %s unread alert email(s).", len(msg_ids))

        for msg_id in msg_ids:
            try:
                typ, data = imap.fetch(msg_id, "(BODY.PEEK[])")  # PEEK: don't auto-mark as read
                if typ != "OK" or not data or not data[0]:
                    continue
                raw_bytes = data[0][1]
                msg = email_lib.message_from_bytes(raw_bytes)
                from_header = _decode_header_value(msg.get("From", "")).lower()
                source_name = "Bayt.com (email)" if "bayt" in from_header else "Tanqeeb.com (email)"

                jobs = _parse_alert_email(raw_bytes, source_name)
                all_jobs.extend(jobs)

                # Only mark as read once we've finished processing it, so a
                # crash mid-run leaves it unread and it gets retried later.
                imap.store(msg_id, "+FLAGS", "\\Seen")
            except Exception:  # noqa: BLE001 - one bad email shouldn't skip the rest
                logger.exception("email: failed to process message id %s", msg_id)
    except imaplib.IMAP4.error:
        logger.exception("email: IMAP error while reading alerts")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass

    logger.info("email: parsed %s job(s) total from alert emails.", len(all_jobs))
    return all_jobs
