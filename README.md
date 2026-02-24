# LinkedIn Auto-Connect & Message Tool

> **Python tool** (CLI + Web UI) that reads LinkedIn profile URLs from a spreadsheet (CSV/XLSX/Google Sheets), sends personalized connection requests, and follows up with a message once accepted — all via Playwright browser automation.

> **Disclaimer:** LinkedIn's Terms of Service prohibit automated interactions. Using this tool carries risk of account restriction or ban. Built-in safety measures (rate limiting, human-like delays, headful browser) reduce but do not eliminate that risk. Use at your own discretion.

---

## Tech Stack

| Component       | Technology                          |
| --------------- | ----------------------------------- |
| Language        | Python 3.10+                        |
| Browser Engine  | Playwright (Chromium, headful)      |
| Spreadsheet I/O | `openpyxl`, `csv`, `gspread`        |
| Database        | SQLite                              |
| Config          | `.env` + `python-dotenv`            |
| CLI             | `argparse` + `rich`                 |
| Web UI          | Flask + Bootstrap 5 (dark theme)    |
| Auth            | Flask-Login + Flask-WTF             |

---

## Project Structure

```
Linkedin-help/
├── app.py                   # Flask web app entry point
├── main.py                  # CLI entry point
├── config.py                # Settings, delays, caps, template paths
├── spreadsheet_reader.py    # Unified CSV / XLSX / Google Sheets reader
├── linkedin_bot.py          # Playwright automation (login, connect, message)
├── db.py                    # SQLite persistence & progress tracking (CLI)
├── console.py               # Rich console UI (progress bars, tables, colors)
├── logger.py                # File logging to logs/run_YYYY-MM-DD.log
├── requirements.txt         # Python dependencies
├── Dockerfile               # Docker deployment
├── Procfile                 # Railway / Render deployment
├── .env                     # LinkedIn credentials (GIT-IGNORED)
├── web/
│   ├── __init__.py
│   ├── models.py            # SQLAlchemy models (User, Job, JobProfile)
│   ├── forms.py             # WTForms for auth & settings
│   ├── auth.py              # Register / Login / Logout blueprint
│   ├── dashboard.py         # Dashboard, upload, job management blueprint
│   ├── worker.py            # Background bot worker (threaded)
│   ├── templates/
│   │   ├── base.html        # Dark-themed Bootstrap layout
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   └── register.html
│   │   └── dashboard/
│   │       ├── index.html   # Job list dashboard
│   │       ├── upload.html  # CSV upload + mode selection
│   │       ├── job.html     # Job detail + live progress
│   │       └── settings.html # Templates + LinkedIn session
│   └── static/
├── templates/
│   ├── connection_note.txt  # Template for connection request note
│   └── followup_message.txt # Template for follow-up message
├── logs/                    # Daily log files (GIT-IGNORED)
└── tests/
    ├── test_spreadsheet.py  # Unit tests for reader
    ├── test_db.py           # Unit tests for database
    ├── test_console.py      # Unit tests for rich console UI
    ├── test_logger.py       # Unit tests for file logging
    ├── test_main.py         # Unit tests for CLI & export
    └── sample_urls.csv      # Sample data for testing
```

---

## Web UI (Multi-User)

The tool includes a full web interface for multi-user deployment.

### Quick Start (Local)

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Run the web app
python app.py
# → Open http://localhost:5000
```

### Quick Start (Docker)

```bash
docker build -t linkedin-helper .
docker run -p 5000:5000 -e SECRET_KEY=your-secret-key linkedin-helper
```

### Deploy to Railway / Render

1. Push to GitHub
2. Connect your repo on [Railway](https://railway.app) or [Render](https://render.com)
3. Set environment variable: `SECRET_KEY=<random-string>`
4. Deploy — the Dockerfile handles everything

### Web UI Features

| Feature | Description |
|---------|-------------|
| **User Accounts** | Register/login — each user has isolated data |
| **CSV Upload** | Upload a CSV with LinkedIn URLs |
| **Job Modes** | Connect, Message, or Both |
| **Live Progress** | Real-time progress bar + status updates |
| **LinkedIn Session** | Paste your `state.json` in Settings |
| **Custom Templates** | Edit connection note & follow-up message per user |
| **Export Results** | Download job results as CSV |
| **Cancel Jobs** | Stop a running job anytime |

### How It Works

1. **Register** an account on the web UI
2. Go to **Settings** → paste your LinkedIn `state.json` session
3. Customize your **connection note** and **follow-up message** templates
4. Go to **New Job** → upload a CSV → choose mode → Create
5. Click **Start** — watch live progress as profiles are processed
6. **Export** results when done

---

## CLI Usage

The original CLI is still available for direct use:

---

## Phases

### Phase 1 — Project Setup, Config & Spreadsheet Reader

**Goal:** Scaffold the project, install dependencies, and build the spreadsheet ingestion layer.

**Deliverables:**

- `requirements.txt` with all dependencies
- `.gitignore` (ignore `.env`, `state.json`, `*.db`, `__pycache__/`)
- `.env` template with `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` placeholders
- `config.py` — all tunable constants:
  - `DELAY_BETWEEN_PROFILES = (45, 90)` seconds (random range)
  - `DELAY_BETWEEN_ACTIONS = (2, 5)` seconds
  - `LONG_PAUSE_EVERY_N = 10` profiles
  - `LONG_PAUSE_DURATION = (300, 600)` seconds (5–10 min)
  - `DAILY_CONNECTION_CAP = 20`
  - `DAILY_MESSAGE_CAP = 50`
  - Template file paths
- `templates/connection_note.txt` — e.g. `Hi {first_name}, I'd love to connect and exchange ideas!`
- `templates/followup_message.txt` — e.g. `Hi {first_name}, thanks for connecting! I wanted to ...`
- `spreadsheet_reader.py`:
  - `read_spreadsheet(file_path: str) -> list[dict]` — auto-detects format by extension
  - CSV support (built-in `csv` module)
  - XLSX support (`openpyxl`)
  - Google Sheets support (`gspread` + service account JSON)
  - URL validation: must match `https://(www\.)?linkedin\.com/in/...` pattern
  - Returns `[{"url": "...", "row": 1}, ...]`
- `tests/sample_urls.csv` — 5 sample LinkedIn URLs for testing
- `tests/test_spreadsheet.py` — unit tests for all 3 formats

**Verification:**

```bash
pip install -r requirements.txt
python -m pytest tests/test_spreadsheet.py -v
```

---

### Phase 2 — SQLite Database Layer

**Goal:** Build the persistence layer that tracks every profile's status and enforces daily caps.

**Deliverables:**

- `db.py` with class `Database`:
  - `__init__(db_path="progress.db")` — creates DB + tables if not exist
  - Table `profiles`: `id`, `url`, `name`, `status` (pending | request_sent | connected | messaged | skipped | error), `error_msg`, `created_at`, `updated_at`
  - Table `daily_counters`: `date`, `connections_sent`, `messages_sent`
  - `import_urls(urls: list[dict])` — bulk upsert (skip duplicates)
  - `get_pending_profiles(limit: int) -> list[dict]` — fetch next batch
  - `get_accepted_profiles(limit: int) -> list[dict]` — profiles with `request_sent` status (for messaging pass)
  - `update_status(url, status, name=None, error_msg=None)`
  - `increment_daily_counter(counter_type: str)` — bump today's count
  - `get_daily_count(counter_type: str) -> int` — today's count
  - `is_daily_cap_reached(counter_type: str) -> bool`
  - `get_summary() -> dict` — counts by status
  - Context manager support (`with Database() as db:`)
- `tests/test_db.py` — unit tests for all DB operations

**Verification:**

```bash
python -m pytest tests/test_db.py -v
# Manual: python -c "from db import Database; db = Database(); print(db.get_summary())"
```

---

### Phase 3 — Playwright Login & Browser Session Management

**Goal:** Set up Playwright browser launch, manual LinkedIn login, and persistent session (cookies) storage.

**Deliverables:**

- `linkedin_bot.py` with class `LinkedInBot`:
  - `__init__(headless=False)` — configures Playwright Chromium launch args
  - `start()` — launches browser. If `state.json` exists, loads saved cookies/storage. Navigates to `linkedin.com/feed` to verify logged-in state.
  - `login()` — navigates to LinkedIn login page, **pauses execution** (`page.pause()` or input prompt) for user to manually log in + handle 2FA/CAPTCHA, then saves browser state to `state.json`
  - `is_logged_in() -> bool` — checks if feed page loads (vs redirect to login)
  - `close()` — saves state and closes browser
  - Anti-detection basics: standard viewport (1280×800), real user-agent string, disable `navigator.webdriver` flag
  - `_random_delay(range_tuple)` — async sleep with random jitter
  - Context manager support
- Install Playwright browsers (`playwright install chromium`)

**Verification:**

```bash
playwright install chromium
python -c "from linkedin_bot import LinkedInBot; bot = LinkedInBot(); bot.start(); bot.login(); bot.close()"
# Should open browser, let you log in manually, save session, close.
# Run again — should skip login and go straight to feed.
```

---

### Phase 4 — Connection Request Automation

**Goal:** Implement the core logic to visit each profile and send a personalized connection request with a note.

**Deliverables:**

- Add to `LinkedInBot`:
  - `visit_profile(url: str) -> dict` — navigates to profile, extracts `first_name` from the `<h1>` heading, returns `{"name": "...", "first_name": "..."}`
  - `send_connection_request(url: str, note_template: str) -> str` — full flow:
    1. Visit profile
    2. Detect current state: "Connect" button visible, already "Pending", already "Connected", or "Follow" only
    3. If "Connect" found: click it → wait for note modal → fill personalized note (`{first_name}` replaced) → click "Send"
    4. If "More" dropdown needed: click "More" → find "Connect" in dropdown → proceed
    5. Return status string: `request_sent`, `already_pending`, `already_connected`, `skipped`, `error`
  - Handle edge cases:
    - Profile doesn't exist (404/removed) → return `error`
    - "Follow" instead of "Connect" (open profile / creator) → return `skipped`
    - Note exceeds 300 chars → truncate gracefully
    - LinkedIn "weekly limit reached" banner → return `cap_reached` + stop
  - Integrate with `Database`: update status after each profile
  - Integrate with `config.py`: respect delays and daily caps
  - Random delay between each profile + long pause every N profiles

**Verification:**

```bash
# Create a test CSV with 3 URLs of people you want to connect with
python main.py --file test_3.csv --mode connect --dry-run
# Dry run: visits profiles, logs names + intended actions, clicks nothing

python main.py --file test_3.csv --mode connect
# Live run: should send 3 connection requests with personalized notes
```

---

### Phase 5 — Follow-Up Message Automation

**Goal:** Implement detection of accepted connections and sending personalized follow-up messages.

**Deliverables:**

- Add to `LinkedInBot`:
  - `check_connection_status(url: str) -> str` — visit profile, detect if now connected (Message button visible) or still pending
  - `send_followup_message(url: str, message_template: str) -> str` — full flow:
    1. Visit profile
    2. Verify "Message" button exists (means connected)
    3. Click "Message" → wait for chat modal
    4. Type personalized message (`{first_name}` replaced) with human-like character-by-character typing (random delay per keystroke)
    5. Click "Send"
    6. Close chat modal
    7. Return status: `messaged`, `not_connected`, `error`
  - Handle edge cases:
    - Chat modal doesn't open → retry once → error
    - Profile has messaging restricted → skip
    - Premium InMail prompt instead of free message → skip
  - Integrate with `Database`: update status to `messaged`
  - Integrate daily message cap from `config.py`
- Add `--mode message` support: queries DB for `request_sent` profiles, checks if accepted, messages if yes
- Add `--mode both` support: runs connect pass first, then message pass on newly accepted ones

**Verification:**

```bash
# After Phase 4 connections have been accepted:
python main.py --file test_3.csv --mode message --dry-run
# Should detect which are now connected and log intended messages

python main.py --file test_3.csv --mode message
# Live: sends personalized follow-up to accepted connections
```

---

### Phase 6 — CLI Polish, Status Dashboard & Final Testing ✅

**Goal:** Build the full CLI interface, rich console dashboard, logging, and end-to-end testing.

**Deliverables:**

- `console.py` — Rich console UI module:
  - Color-coded status messages: green (✓ success), yellow (○ skipped), red (✗ error), cyan (ℹ info)
  - Styled banners with DRY RUN indicator
  - Live progress bar (`rich.progress`) with ETA, spinner, and counter
  - Session summary table (processed, sent, skipped, errors)
  - Database summary table (counts by status)
  - Full status dashboard with cap usage bars and recent activity
  - Safe markup escaping for all user-provided text
- `logger.py` — File logging module:
  - Creates `logs/` directory automatically
  - Writes to `logs/run_YYYY-MM-DD.log` (appends to daily file)
  - Format: `timestamp | LEVEL | message`
  - Idempotent setup (no duplicate handlers)
- `main.py` — Full CLI with `argparse`:
  - `python main.py --file <path> --mode connect|message|both` — main automation
  - `python main.py --status` — show rich dashboard (tables, cap bars, activity)
  - `python main.py --reset-errors` — reset all `error` profiles back to `pending`
  - `python main.py --export results.csv` — export DB to CSV with all columns
  - `--dry-run` flag — simulates without clicking
  - `--cap <number>` — override daily cap for this run
  - `--delay <seconds>` — override minimum delay between profiles
- Graceful Ctrl+C handling:
  - SIGINT handler sets a flag, current profile finishes cleanly
  - Session summary always printed on exit
  - Browser and DB connections closed properly
- Tests: `test_console.py` (24 tests), `test_logger.py` (8 tests), `test_main.py` (14 tests)

**Verification:**

```bash
python main.py --file urls.xlsx --mode connect
# Full run with progress bar, logging, cap enforcement

python main.py --status
# Pretty table: Pending: 980 | Sent: 20 | Connected: 0 | Messaged: 0 | Errors: 0

python main.py --export results.csv
# CSV with all 1000 rows and their current status

# Ctrl+C mid-run → restart → should resume from where it stopped
```

---

## Quick Start (after all phases built)

```bash
# 1. Clone & install
cd Linkedin-help
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env with your LinkedIn email/password (used only for reference)
# Edit templates/connection_note.txt and followup_message.txt

# 3. First run — login
python main.py --file urls.xlsx --mode connect
# Browser opens → log in manually → tool saves session → starts sending

# 4. Check progress
python main.py --status

# 5. Send follow-up messages (after connections accepted)
python main.py --file urls.xlsx --mode message

# 6. Export results
python main.py --export results.csv
```

---

## Safety Settings (config.py)

| Setting                  | Default   | Description                        |
| ------------------------ | --------- | ---------------------------------- |
| `DAILY_CONNECTION_CAP`   | 20        | Max connection requests per day    |
| `DAILY_MESSAGE_CAP`      | 50        | Max messages per day               |
| `DELAY_BETWEEN_PROFILES` | 45–90 sec | Random wait between each profile   |
| `DELAY_BETWEEN_ACTIONS`  | 2–5 sec   | Random wait between clicks/typing  |
| `LONG_PAUSE_EVERY_N`     | 10        | Take a long break every N profiles |
| `LONG_PAUSE_DURATION`    | 5–10 min  | Duration of the long break         |

---

## Phase Summary

| Phase | Name                               | Key Files                            |
| ----- | ---------------------------------- | ------------------------------------ |
| 1     | Project Setup & Spreadsheet Reader | `config.py`, `spreadsheet_reader.py` |
| 2     | SQLite Database Layer              | `db.py`                              |
| 3     | Browser Login & Session Management | `linkedin_bot.py` (login)            |
| 4     | Connection Request Automation      | `linkedin_bot.py` (connect)          |
| 5     | Follow-Up Message Automation       | `linkedin_bot.py` (message)          |
| 6     | CLI Polish & Status Dashboard      | `main.py`, logging, rich UI          |

> **Estimated total runtime:** ~1000 URLs × 60s average = ~17 hours of browser time spread across ~50 days at 20 connections/day.
