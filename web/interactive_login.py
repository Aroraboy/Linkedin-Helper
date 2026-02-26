"""
interactive_login.py — Server-side interactive browser for LinkedIn login.

Launches a Playwright browser, takes screenshots, and forwards user
click/keyboard events. The user sees a live view of the LinkedIn login
page inside the app and interacts with it directly.
"""

import base64
import json
import time
import traceback
from threading import Lock
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

# Stealth JS
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""

# Store active sessions: {user_id: InteractiveSession}
_sessions: dict[int, "InteractiveSession"] = {}
_lock = Lock()


class InteractiveSession:
    """Manages a live Playwright browser session for a user."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.pw = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.active = False
        self.error: Optional[str] = None
        self._lock = Lock()

    def start(self):
        """Launch browser and navigate to LinkedIn login."""
        try:
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--no-zygote",
                    "--disable-setuid-sandbox",
                    "--disable-accelerated-2d-canvas",
                ],
            )
            self.context = self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self.page = self.context.new_page()
            self.page.add_init_script(STEALTH_JS)
            self.page.goto(
                "https://www.linkedin.com/login",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            self.active = True
        except Exception as e:
            self.error = str(e)
            traceback.print_exc()
            self.close()

    def screenshot(self) -> Optional[str]:
        """Take a screenshot in base64 PNG format."""
        with self._lock:
            if not self.active or not self.page:
                return None
            try:
                img_bytes = self.page.screenshot(type="jpeg", quality=60)
                return base64.b64encode(img_bytes).decode("utf-8")
            except Exception:
                return None

    def click(self, x: int, y: int):
        """Click at coordinates."""
        with self._lock:
            if not self.active or not self.page:
                return
            try:
                self.page.mouse.click(x, y)
            except Exception:
                pass

    def type_text(self, text: str):
        """Type text into the currently focused element."""
        with self._lock:
            if not self.active or not self.page:
                return
            try:
                self.page.keyboard.type(text, delay=50)
            except Exception:
                pass

    def press_key(self, key: str):
        """Press a special key (Enter, Tab, Backspace, etc.)."""
        with self._lock:
            if not self.active or not self.page:
                return
            try:
                self.page.keyboard.press(key)
            except Exception:
                pass

    def get_url(self) -> str:
        """Get the current page URL."""
        with self._lock:
            if not self.page:
                return ""
            try:
                return self.page.url
            except Exception:
                return ""

    def is_logged_in(self) -> bool:
        """Check if we've reached LinkedIn feed (login successful)."""
        url = self.get_url()
        return "/feed" in url or "/mynetwork" in url

    def extract_session(self) -> Optional[str]:
        """Extract storage state (cookies + localStorage) as JSON."""
        with self._lock:
            if not self.context:
                return None
            try:
                state = self.context.storage_state()
                return json.dumps(state, indent=2)
            except Exception:
                return None

    def close(self):
        """Clean up browser resources."""
        self.active = False
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass


def get_session(user_id: int) -> Optional[InteractiveSession]:
    """Get the active session for a user."""
    with _lock:
        return _sessions.get(user_id)


def start_session(user_id: int) -> InteractiveSession:
    """Start a new interactive login session for a user."""
    with _lock:
        # Close existing session if any
        if user_id in _sessions:
            try:
                _sessions[user_id].close()
            except Exception:
                pass

        session = InteractiveSession(user_id)
        _sessions[user_id] = session

    session.start()
    return session


def close_session(user_id: int):
    """Close and remove a user's session."""
    with _lock:
        session = _sessions.pop(user_id, None)
        if session:
            session.close()
