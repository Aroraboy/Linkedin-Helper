"""
config.py — Central configuration for the LinkedIn Auto-Connect & Message Tool.
All tunable constants live here. Override via CLI flags or environment variables.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = BASE_DIR / "progress.db"
STATE_PATH = BASE_DIR / "state.json"

# ─── LinkedIn Credentials (reference only — login is manual) ──────────────────
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

# ─── Delay Settings (seconds) ────────────────────────────────────────────────
# Random delay between processing each profile (min, max)
DELAY_BETWEEN_PROFILES = (45, 90)

# Random delay between individual page actions like clicks and typing (min, max)
DELAY_BETWEEN_ACTIONS = (2, 5)

# After every N profiles, take a long pause to appear more human
LONG_PAUSE_EVERY_N = 10

# Duration of the long pause (min, max) in seconds (default: 5–10 minutes)
LONG_PAUSE_DURATION = (300, 600)

# ─── Daily Caps ──────────────────────────────────────────────────────────────
# Maximum connection requests to send per day (LinkedIn soft-limits ~100/week)
DAILY_CONNECTION_CAP = 20

# Maximum follow-up messages to send per day
DAILY_MESSAGE_CAP = 50

# ─── Template Files ──────────────────────────────────────────────────────────
CONNECTION_NOTE_TEMPLATE_FILE = TEMPLATES_DIR / "connection_note.txt"
FOLLOWUP_MESSAGE_TEMPLATE_FILE = TEMPLATES_DIR / "followup_message.txt"

# ─── Browser Settings ────────────────────────────────────────────────────────
HEADLESS = False  # True = invisible browser (risky), False = visible browser (safer)
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ─── LinkedIn URLs ───────────────────────────────────────────────────────────
LINKEDIN_BASE_URL = "https://www.linkedin.com"
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"

# ─── Profile Statuses ───────────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_REQUEST_SENT = "request_sent"
STATUS_CONNECTED = "connected"
STATUS_MESSAGED = "messaged"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"
STATUS_CAP_REACHED = "cap_reached"

ALL_STATUSES = [
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
    STATUS_CONNECTED,
    STATUS_MESSAGED,
    STATUS_SKIPPED,
    STATUS_ERROR,
]


def load_template(template_path: Path) -> str:
    """Load a message template from a text file."""
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")
    return template_path.read_text(encoding="utf-8").strip()


def get_connection_note_template() -> str:
    """Load the connection request note template."""
    return load_template(CONNECTION_NOTE_TEMPLATE_FILE)


def get_followup_message_template() -> str:
    """Load the follow-up message template."""
    return load_template(FOLLOWUP_MESSAGE_TEMPLATE_FILE)
