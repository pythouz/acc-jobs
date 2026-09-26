# Riyadh Accounting Job Alerts

Watches for accounting (`محاسب`) jobs in **Riyadh** (`الرياض`) and pushes new
postings to a Telegram chat — no server required, runs on a GitHub Actions
schedule.

**How it finds jobs:** Bayt.com and Tanqeeb.com both sit behind bot
protection (Bayt uses Cloudflare) that blocks requests coming from
data-center IPs — including GitHub Actions runners — regardless of request
headers. So instead of scraping their pages directly, this reads each
site's own **official job-alert emails** from a Gmail inbox over IMAP. The
site does the search and matching itself and emails you; this script just
reads that inbox and forwards new postings to Telegram.

## Files

| File                              | Purpose                                                |
|------------------------------------|-----------------------------------------------------------|
| `scraper.py`                       | Orchestrates sources, relevance filter, dedup, sends alerts |
| `email_alerts.py`                   | Reads Bayt/Tanqeeb alert emails from Gmail via IMAP         |
| `telegram_bot.py`                   | Sends HTML-formatted Telegram alerts                       |
| `utils.py`                          | Small helpers shared by the parsers                        |
| `config.py`                         | All tunable settings (keywords, sender hints, etc.)        |
| `seen_jobs.json`                    | Persisted set of job IDs already alerted on                |
| `.github/workflows/scraper.yml`     | Cron schedule + commit-back step                           |
| `requirements.txt`                  | `requests` + `beautifulsoup4` (IMAP/email are built into Python) |

A direct website scraper (`scrape_bayt` / `scrape_tanqeeb` in `scraper.py`)
is also included and still works end-to-end, but is **off by default**
because of the Cloudflare block described above. It might be worth
re-enabling in `config.py` if you ever run this from a home network instead
of GitHub Actions, where a residential IP is far less likely to be blocked.

## How it works

1. `email_alerts.py` logs into Gmail over IMAP and searches for **unread**
   emails whose sender contains `bayt.com` or `tanqeeb.com`.
2. For each one, it reads the HTML body and extracts job entries (title,
   company, location, link), then flags that email as read so it isn't
   processed again.
3. Every job — from any source — passes through `is_relevant()`, a
   safety-net check that it actually mentions an accounting term *and*
   Riyadh.
4. New jobs (IDs not already in `seen_jobs.json`) are sent to Telegram; only
   ones that send successfully get recorded, so a Telegram outage doesn't
   silently drop a posting.
5. The GitHub Actions workflow runs this on a cron schedule and commits the
   updated `seen_jobs.json` back to the repo so state survives between runs.

## Setup

### 1. Turn on job alerts on Bayt and Tanqeeb
On each site, search **"Accountant"** / **"محاسب"** in **Riyadh**, and turn on
their built-in email job-alert feature, pointed at the Gmail address you'll
use below (the one you told me: your Gmail account).

### 2. Create a Gmail App Password (not your normal password)
1. Turn on **2-Step Verification** on that Google account if it isn't on
   already: https://myaccount.google.com/signinoptions/two-step-verification
2. Go to https://myaccount.google.com/apppasswords and create a new app
   password (name it something like "job-scraper"). Google gives you a
   16-character code — copy it.
3. This code is scoped to just this integration. It's separate from your
   real password and you can revoke it any time from that same page without
   affecting your Google account login.

*(If "App Passwords" isn't visible, IMAP access may be off — check
Gmail → Settings → "See all settings" → "Forwarding and POP/IMAP" tab →
enable IMAP.)*

### 3. Add secrets to your GitHub repo
Go to **Settings → Secrets and variables → Actions** and add four repository
secrets:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GMAIL_ADDRESS` — the Gmail address itself (e.g. `you@gmail.com`)
- `GMAIL_APP_PASSWORD` — the 16-character code from step 2 (never the
  regular Google password)

### 4. Enable write permissions for Actions
**Settings → Actions → General → Workflow permissions** → select **"Read and
write permissions"** — needed so the workflow can commit `seen_jobs.json`
back.

### 5. Run it
It runs automatically every 2 hours. Trigger it manually any time from the
**Actions** tab (`workflow_dispatch`) to test.

## Running locally

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123456:ABC-your-token"
export TELEGRAM_CHAT_ID="123456789"
export GMAIL_ADDRESS="you@gmail.com"
export GMAIL_APP_PASSWORD="the 16-character app password"
python scraper.py
```

## What this touches in your mailbox

Read-only, with one exception: once it successfully reads an unread
Bayt/Tanqeeb alert email, it flags that single email as read so it isn't
processed again next run. It never deletes, sends, labels, or looks at any
other mail. On the very first run, any alert emails already sitting unread
in the inbox will be processed too (so you may get a small backlog of
alerts sent to Telegram once, the first time it runs).

## If it stops finding jobs inside alert emails (selector drift)

Bayt/Tanqeeb can change the template of their alert emails at any time. If a
run finds unread emails but extracts 0 jobs from them:
1. Run locally with debugging on:
   ```bash
   SCRAPER_DEBUG=1 python scraper.py
   ```
   This saves the raw HTML of every processed email into `debug_html/`.
2. Open one, see how job entries are actually laid out, and add the new
   selector to the matching list near the top of `email_alerts.py`
   (`CARD_SELECTORS`, `TITLE_SELECTORS`, etc. — tried in order, so just
   append). There's also a link-based fallback (`JOB_LINK_HINT`) that
   catches most formats even without a card selector match.

## Notes and limits

- **Contact info**: alert emails don't typically include a direct email or
  phone number, so `contact` will usually read "Not available".
- **`seen_jobs.json` size**: keeps only the most recent `MAX_SEEN_JOBS`
  (default 2000) IDs; older ones are dropped automatically.
- This is a best-effort integration against a template that can change
  without notice — budget for occasionally updating a selector (see above),
  not a "set and forget forever" system.
