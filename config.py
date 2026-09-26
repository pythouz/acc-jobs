"""
Central configuration for the job scraper.

Nothing in here talks to the network; it just holds the knobs the rest
of the code reads from. Edit values here rather than hunting through
scraper.py / telegram_bot.py.
"""

import os

# --- Search parameters -------------------------------------------------
# Bayt's site is served in English/Arabic by locale; its SEO-style URLs
# read naturally with an English keyword. Tanqeeb's Saudi site is
# Arabic-first, so an Arabic keyword matches how job titles are written.
BAYT_KEYWORD = "accountant"
BAYT_LOCATION_SLUG = "riyadh"

TANQEEB_KEYWORD = "محاسب"
TANQEEB_LOCATION = "الرياض"

# Terms used by the extra relevance safety-net filter (kept separate
# from the search keywords above so it also catches synonyms).
RELEVANCE_KEYWORDS = ["محاسب", "محاسبة", "accountant", "accounting", "finance"]
RELEVANCE_LOCATIONS = ["الرياض", "riyadh"]

# --- Sources -------------------------------------------------------------
SOURCES_ENABLED = {
    "bayt": True,
    "tanqeeb": True,
}

# --- Files -----------------------------------------------------------------
SEEN_JOBS_FILE = "seen_jobs.json"
MAX_SEEN_JOBS = 2000  # oldest IDs beyond this are dropped so the file stays small

# --- Networking --------------------------------------------------------------
REQUEST_TIMEOUT = 20  # seconds
REQUEST_DELAY = 2  # seconds of politeness delay between requests
MAX_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --- Telegram ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Debugging -----------------------------------------------------------------
# Set SCRAPER_DEBUG=1 in the environment to dump every fetched page's raw
# HTML into DEBUG_DIR, so selectors can be re-checked against real markup.
DEBUG_SAVE_HTML = os.environ.get("SCRAPER_DEBUG", "0") == "1"
DEBUG_DIR = "debug_html"
