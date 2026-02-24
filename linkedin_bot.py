"""
linkedin_bot.py — Playwright-based LinkedIn browser automation.

Handles:
    - Browser launch with anti-detection settings
    - Manual login with session persistence (cookies saved to state.json)
    - Session restoration across runs (no repeated logins)

Future phases will add:
    - Profile visiting & name extraction (Phase 4)
    - Connection request sending (Phase 4)
    - Follow-up messaging (Phase 5)
"""

import json
import random
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config import (
    DELAY_BETWEEN_ACTIONS,
    DELAY_BETWEEN_PROFILES,
    HEADLESS,
    LINKEDIN_FEED_URL,
    LINKEDIN_LOGIN_URL,
    LONG_PAUSE_DURATION,
    LONG_PAUSE_EVERY_N,
    STATE_PATH,
    USER_AGENT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)


class LinkedInBot:
    """
    Playwright-based browser automation for LinkedIn.

    Usage:
        with LinkedInBot() as bot:
            bot.start()
            # ... automation actions ...

    Or manually:
        bot = LinkedInBot()
        bot.start()
        bot.close()
    """

    def __init__(self, headless: Optional[bool] = None, state_path: Optional[str] = None):
        """
        Initialize the bot configuration (does NOT launch the browser yet).

        Args:
            headless: Override config.HEADLESS. False = visible browser (safer).
            state_path: Override path for session storage file.
        """
        self.headless = headless if headless is not None else HEADLESS
        self.state_path = Path(state_path) if state_path else STATE_PATH

        # These are set when start() is called
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    def page(self) -> Page:
        """Get the current browser page. Raises if browser not started."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call bot.start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """Get the current browser context."""
        if self._context is None:
            raise RuntimeError("Browser not started. Call bot.start() first.")
        return self._context

    # ─── Context Manager ─────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ─── Browser Lifecycle ───────────────────────────────────────────────────

    def start(self) -> bool:
        """
        Launch the browser and restore session if available.

        Returns:
            True if already logged in (session restored), False if login needed.
        """
        print("[BOT] Launching browser...")
        self._playwright = sync_playwright().start()

        # Launch Chromium with anti-detection args
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1280,800",
            ],
        )

        # Create context with saved state or fresh
        if self.state_path.exists():
            print(f"[BOT] Restoring session from {self.state_path.name}...")
            try:
                self._context = self._browser.new_context(
                    storage_state=str(self.state_path),
                    viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                    user_agent=USER_AGENT,
                )
            except Exception as e:
                print(f"[BOT] Failed to restore session: {e}")
                print("[BOT] Starting fresh session...")
                self._context = self._create_fresh_context()
        else:
            print("[BOT] No saved session found. Starting fresh...")
            self._context = self._create_fresh_context()

        # Open the first page
        self._page = self._context.new_page()

        # Inject anti-detection scripts
        self._apply_stealth()

        # Check if we're already logged in
        if self.is_logged_in():
            print("[BOT] Session active — already logged in!")
            return True
        else:
            print("[BOT] Not logged in. Manual login required.")
            return False

    def _create_fresh_context(self) -> BrowserContext:
        """Create a new browser context without saved state."""
        return self._browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            user_agent=USER_AGENT,
        )

    def _apply_stealth(self):
        """
        Inject JavaScript to mask automation indicators.
        Makes the browser appear more like a regular user's browser.
        """
        stealth_js = """
        // Override navigator.webdriver to be undefined
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Override chrome runtime to appear normal
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // Override permissions query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Override plugins to appear non-empty
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });

        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        """
        self._page.add_init_script(stealth_js)

    def login(self):
        """
        Navigate to LinkedIn login and wait for the user to log in manually.

        The user should:
            1. Enter their email and password in the browser
            2. Complete any 2FA/CAPTCHA challenges
            3. Wait until the LinkedIn feed loads

        Once logged in, the session is saved to state.json for future runs.
        """
        if self._page is None:
            raise RuntimeError("Browser not started. Call bot.start() first.")

        print("[BOT] Navigating to LinkedIn login page...")
        self._page.goto(LINKEDIN_LOGIN_URL, wait_until="domcontentloaded")
        self._random_delay(DELAY_BETWEEN_ACTIONS)

        print()
        print("=" * 60)
        print("  MANUAL LOGIN REQUIRED")
        print("=" * 60)
        print()
        print("  1. Switch to the browser window")
        print("  2. Log in with your LinkedIn credentials")
        print("  3. Complete any 2FA / CAPTCHA if prompted")
        print("  4. Wait until you see the LinkedIn feed")
        print()
        print("  Once you're on the feed, come back here and press ENTER.")
        print()
        print("=" * 60)

        input("  Press ENTER after you've logged in... ")
        print()

        # Verify login succeeded
        if self.is_logged_in():
            self._save_state()
            print("[BOT] Login successful! Session saved.")
        else:
            print("[BOT] WARNING: Login may not have completed.")
            print("[BOT] The feed page didn't load. Please try again.")
            # Still save state in case it partially worked
            self._save_state()

    def is_logged_in(self) -> bool:
        """
        Check if the user is currently logged in to LinkedIn.

        Navigates to the feed page and checks if it loads successfully
        (vs. redirecting to the login page).

        Returns:
            True if logged in, False otherwise.
        """
        if self._page is None:
            return False

        try:
            print("[BOT] Checking login status...")
            self._page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded", timeout=15000)
            self._random_delay((1, 3))

            current_url = self._page.url

            # If we're on the feed or any authenticated page, we're logged in
            if "/feed" in current_url or "/mynetwork" in current_url:
                return True

            # If we got redirected to login, we're not logged in
            if "/login" in current_url or "/authwall" in current_url or "uas/login" in current_url:
                return False

            # Check for feed-specific elements as a fallback
            try:
                self._page.wait_for_selector(
                    'div.feed-shared-update-v2, [data-test-id="feed"], .scaffold-layout',
                    timeout=5000,
                )
                return True
            except Exception:
                return False

        except Exception as e:
            print(f"[BOT] Error checking login status: {e}")
            return False

    def _save_state(self):
        """Save browser cookies and storage state to disk for session persistence."""
        if self._context is None:
            return

        try:
            state = self._context.storage_state()
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            print(f"[BOT] Session state saved to {self.state_path.name}")
        except Exception as e:
            print(f"[BOT] WARNING: Failed to save session state: {e}")

    def close(self):
        """Save session state and gracefully close the browser."""
        if self._context:
            try:
                self._save_state()
            except Exception:
                pass

        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None

        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        print("[BOT] Browser closed.")

    # ─── Delay Helpers ───────────────────────────────────────────────────────

    def _random_delay(self, delay_range: tuple[float, float]):
        """
        Sleep for a random duration within the given range.
        Adds human-like variability to actions.

        Args:
            delay_range: (min_seconds, max_seconds)
        """
        delay = random.uniform(delay_range[0], delay_range[1])
        time.sleep(delay)

    def action_delay(self):
        """Short delay between page actions (clicks, typing)."""
        self._random_delay(DELAY_BETWEEN_ACTIONS)

    def profile_delay(self):
        """Longer delay between processing different profiles."""
        self._random_delay(DELAY_BETWEEN_PROFILES)

    def long_pause(self):
        """
        Extended pause taken every N profiles to appear more human.
        Prints a countdown so the user knows the tool hasn't frozen.
        """
        pause_seconds = random.uniform(LONG_PAUSE_DURATION[0], LONG_PAUSE_DURATION[1])
        minutes = pause_seconds / 60
        print(f"[BOT] Taking a long break ({minutes:.1f} minutes) to avoid detection...")
        time.sleep(pause_seconds)
        print("[BOT] Break over. Resuming...")

    def should_take_long_pause(self, profile_count: int) -> bool:
        """
        Check if it's time for a long pause based on profiles processed.

        Args:
            profile_count: Number of profiles processed so far in this session.

        Returns:
            True if a long pause should be taken.
        """
        return profile_count > 0 and profile_count % LONG_PAUSE_EVERY_N == 0

    # ─── Navigation Helpers ──────────────────────────────────────────────────

    def navigate_to(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        """
        Navigate to a URL with error handling.

        Args:
            url: The URL to navigate to.
            wait_until: Playwright wait condition ('domcontentloaded', 'load', 'networkidle').
            timeout: Maximum wait time in milliseconds.
        """
        try:
            self.page.goto(url, wait_until=wait_until, timeout=timeout)
            self.action_delay()
        except Exception as e:
            print(f"[BOT] Navigation error for {url}: {e}")
            raise

    def get_current_url(self) -> str:
        """Get the current page URL."""
        return self.page.url
