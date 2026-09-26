"""
Minimal wrapper around the Telegram Bot API for sending job alerts.

Only uses `requests` — no third-party Telegram SDK — to keep the
dependency list short.
"""

from __future__ import annotations

import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _escape_html(text: str) -> str:
    """Escape the characters Telegram's HTML parse mode treats specially.

    Only & < > need escaping for Telegram's (deliberately limited) HTML
    subset — see https://core.telegram.org/bots/api#html-style
    """
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_job_message(job: dict) -> str:
    """Build an HTML-formatted Telegram message for a single job dict."""
    title = _escape_html(job.get("title") or "Untitled position")
    company = _escape_html(job.get("company") or "Not specified")
    location = _escape_html(job.get("location") or "Not specified")
    details = _escape_html(job.get("details") or "")
    contact = _escape_html(job.get("contact") or "Not available")
    url = job.get("url") or ""
    source = _escape_html(job.get("source") or "")

    if len(details) > 600:
        details = details[:600].rstrip() + "…"

    lines = [
        f"🧾 <b>{title}</b>",
        f"🏢 <b>Company:</b> {company}",
        f"📍 <b>Location:</b> {location}",
    ]
    if details:
        lines.append(f"📝 <b>Details:</b> {details}")
    lines.append(f"📞 <b>Contact:</b> {contact}")
    if source:
        lines.append(f"🌐 <b>Source:</b> {source}")
    if url:
        lines.append(f'🔗 <a href="{url}">View / Apply</a>')

    return "\n".join(lines)


def send_message(text: str) -> bool:
    """Send one HTML message to the configured Telegram chat.

    Returns True on success, False if the token/chat ID are missing or
    every retry failed.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set; skipping send."
        )
        return False

    url = TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = requests.post(url, data=payload, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return True
            logger.warning(
                "Telegram API returned %s (attempt %s/%s): %s",
                resp.status_code,
                attempt,
                config.MAX_RETRIES,
                resp.text[:300],
            )
        except requests.RequestException as exc:
            logger.warning(
                "Telegram request failed (attempt %s/%s): %s",
                attempt,
                config.MAX_RETRIES,
                exc,
            )
        time.sleep(2 * attempt)

    logger.error("Giving up sending Telegram message after %s attempts.", config.MAX_RETRIES)
    return False


def send_job_alert(job: dict) -> bool:
    """Format and send a single job dict as a Telegram alert."""
    return send_message(format_job_message(job))
