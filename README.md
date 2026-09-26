# Riyadh Accounting Job Alerts

A lightweight scraper that checks **Bayt.com** and **Tanqeeb.com** for
accounting (`محاسب`) jobs in **Riyadh** (`الرياض`), and pushes new postings
to a Telegram chat via a bot. Runs on a GitHub Actions schedule — no server
required.

## Files

| File                              | Purpose                                             |
|------------------------------------|------------------------------------------------------|
| `scraper.py`                       | Fetches + parses jobs, dedupes, drives the run       |
| `telegram_bot.py`                   | Sends HTML-formatted Telegram alerts                 |
| `config.py`                         | All tunable settings (keywords, timeouts, etc.)      |
| `seen_jobs.json`                    | Persisted set of job IDs already alerted on          |
| `.github/workflows/scraper.yml`     | Cron schedule + commit-back step                     |
| `requirements.txt`                  | `requests` + `beautifulsoup4` only                   |

## How it works

1. `scraper.py` fetches the Bayt and Tanqeeb search-results pages and parses
   title / company / location / snippet / URL out of each job card with
   BeautifulSoup.
2. Every parsed job is run through `is_relevant()` — a safety-net check that
   it actually mentions an accounting term *and* Riyadh — in case a results
   page includes sponsored or off-topic listings.
3. New jobs (IDs not already in `seen_jobs.json`) are sent to Telegram; only
   ones that send successfully get added to `seen_jobs.json`, so a Telegram
   outage doesn't silently drop a posting.
4. The GitHub Actions workflow runs this on a cron schedule and commits the
   updated `seen_jobs.json` back to the repo so state survives between runs.

## Setup

1. **Create a Telegram bot** via [@BotFather](https://t.me/BotFather) and
   note the token it gives you.
2. **Get your chat ID**: message your new bot once, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read the
   `"chat":{"id": ...}` value (or use a helper bot like @userinfobot).
3. In your GitHub repo, go to **Settings → Secrets and variables → Actions**
   and add two repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Push this project to the repo.
5. Go to **Settings → Actions → General → Workflow permissions** and select
   **"Read and write permissions"** — the workflow needs this to commit
   `seen_jobs.json` back.
6. It now runs automatically every 2 hours. You can also trigger it anytime
   from the **Actions** tab (`workflow_dispatch`).

## Running locally

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123456:ABC-your-token"
export TELEGRAM_CHAT_ID="123456789"
python scraper.py
```

## If a source stops returning jobs (selector drift)

Job boards change their HTML from time to time, and neither site offers a
public search API, so this scraper only sees whatever server-rendered HTML
a plain `requests.get()` receives. If a source suddenly returns 0 parsed
jobs:

1. Run locally with debugging on:
   ```bash
   SCRAPER_DEBUG=1 python scraper.py
   ```
   This saves every fetched page's raw HTML into `debug_html/`.
2. Open that file next to the live site in your browser's dev tools, find
   the current class/tag names used for the job cards, title link, company,
   location, and snippet.
3. Add the new selector to the matching `*_SELECTORS` list near the top of
   `scraper.py` (they're tried in order — just append, no need to remove the
   old one). No other code needs to change.

## Notes and limits

- **Contact info**: neither site typically publishes an email or phone
  number directly on the listing page, so `contact` will usually read "Not
  available" unless a card explicitly includes one — this is intentional
  rather than a parsing gap.
- **Respectful scraping**: requests use a realistic browser User-Agent, a
  short delay between requests, retries with backoff, and target only the
  two sources you asked for. Review each site's Terms of Service before
  relying on this long-term, and back off the schedule if you see repeated
  errors or blocks.
- **`seen_jobs.json` size**: keeps only the most recent `MAX_SEEN_JOBS`
  (default 2000) IDs; older ones are dropped automatically so the file
  doesn't grow forever.
- This is a best-effort scraper against sites that can change without
  notice — budget for occasionally updating a selector (see above), not a
  "set and forget forever" system.
