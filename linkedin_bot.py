"""
linkedin_bot.py — Playwright-based LinkedIn browser automation.

Handles:
    - Browser launch with anti-detection settings
    - Manual login with session persistence (cookies saved to state.json)
    - Session restoration across runs (no repeated logins)
    - Profile visiting & name extraction
    - Connection request sending with personalized notes

Future phases will add:
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
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
    STATUS_SKIPPED,
    USER_AGENT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    get_connection_note_template,
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

    # ─── Profile Visiting ────────────────────────────────────────────────────

    def visit_profile(self, url: str) -> dict:
        """
        Navigate to a LinkedIn profile and extract the person's name.

        Args:
            url: Full LinkedIn profile URL (e.g. https://www.linkedin.com/in/johndoe)

        Returns:
            dict: {"name": "John Doe", "first_name": "John", "url": url}

        Raises:
            Exception if profile not found or navigation fails.
        """
        self.navigate_to(url)
        self.action_delay()

        current_url = self.get_current_url()

        # Check for 404 / profile not found
        if "/404" in current_url or "page-not-found" in current_url:
            raise ProfileNotFoundError(f"Profile not found: {url}")

        # Check if we got redirected to login (session expired)
        if "/login" in current_url or "/authwall" in current_url:
            raise SessionExpiredError("Session expired — redirected to login page")

        # Extract name from the profile heading
        name = self._extract_profile_name()
        first_name = name.split()[0] if name else "there"

        return {"name": name, "first_name": first_name, "url": url}

    def _extract_profile_name(self) -> str:
        """
        Extract the person's name from the profile page.
        Tries multiple selectors since LinkedIn's DOM varies.

        Returns:
            The person's full name, or empty string if not found.
        """
        selectors = [
            "h1.text-heading-xlarge",                    # Most common
            "h1.inline.t-24",                            # Older layout
            'h1[data-anonymize="person-name"]',          # Some variants
            "div.ph5 h1",                                # Wrapper-based
            ".pv-top-card h1",                           # Top card
            "h1",                                        # Fallback: first h1
        ]

        for selector in selectors:
            try:
                el = self.page.wait_for_selector(selector, timeout=3000)
                if el:
                    text = el.inner_text().strip()
                    if text and len(text) < 100:  # Sanity check
                        return text
            except Exception:
                continue

        print("[BOT] WARNING: Could not extract profile name")
        return ""

    # ─── Connection Requests ─────────────────────────────────────────────────

    def send_connection_request(self, url: str, note_template: Optional[str] = None) -> str:
        """
        Visit a profile and send a connection request with a personalized note.

        Args:
            url: LinkedIn profile URL.
            note_template: Message template with {first_name} placeholder.
                          If None, loads from templates/connection_note.txt.

        Returns:
            Status string: "request_sent", "already_pending", "already_connected",
                          "skipped", "error", "cap_reached"
        """
        if note_template is None:
            note_template = get_connection_note_template()

        try:
            # Step 1: Visit the profile and get the name
            profile_info = self.visit_profile(url)
            first_name = profile_info["first_name"]
            print(f"[BOT]   Name: {profile_info['name']}")

        except ProfileNotFoundError:
            print(f"[BOT]   Profile not found (404)")
            return STATUS_ERROR

        except SessionExpiredError:
            print(f"[BOT]   Session expired! Need to re-login.")
            return STATUS_ERROR

        except Exception as e:
            print(f"[BOT]   Error visiting profile: {e}")
            return STATUS_ERROR

        try:
            # Step 2: Detect the current connection state
            state = self._detect_connection_state()
            print(f"[BOT]   Connection state: {state}")

            if state == "already_connected":
                return "already_connected"
            elif state == "already_pending":
                return "already_pending"
            elif state == "no_connect_button":
                print(f"[BOT]   No Connect button found (Follow-only or restricted profile)")
                return STATUS_SKIPPED

            # Step 3: Click Connect (may be behind "More" dropdown)
            clicked = self._click_connect_button(state)
            if not clicked:
                print("[BOT]   Failed to click Connect button")
                return STATUS_ERROR

            self.action_delay()

            # Step 4: Handle the connection modal (add note + send)
            personalized_note = note_template.format(first_name=first_name)

            # LinkedIn limits notes to 300 characters
            if len(personalized_note) > 300:
                personalized_note = personalized_note[:297] + "..."
                print(f"[BOT]   Note truncated to 300 chars")

            sent = self._handle_connection_modal(personalized_note)
            if sent:
                print(f"[BOT]   Connection request sent!")
                return STATUS_REQUEST_SENT
            else:
                print("[BOT]   Failed to send connection request")
                return STATUS_ERROR

        except LinkedInCapReachedError:
            print("[BOT]   LinkedIn weekly invitation limit reached!")
            return "cap_reached"

        except Exception as e:
            print(f"[BOT]   Error sending connection request: {e}")
            return STATUS_ERROR

    def _detect_connection_state(self) -> str:
        """
        Detect the current connection state with this profile.

        Returns:
            "connect_visible"   — Connect button is directly visible
            "connect_in_more"   — Connect is hidden in the "More" dropdown
            "already_pending"   — Invitation already sent (Pending)
            "already_connected" — Already connected (Message button prominent)
            "no_connect_button" — No connect option found (Follow-only, etc.)
        """
        page = self.page

        # Check for "Pending" state
        try:
            pending = page.query_selector(
                'button:has-text("Pending"), '
                'span:has-text("Pending")'
            )
            if pending and pending.is_visible():
                return "already_pending"
        except Exception:
            pass

        # Check for direct "Connect" button in the main action bar
        try:
            connect_btn = page.query_selector(
                'button.pvs-profile-actions__action:has-text("Connect"), '
                'button[aria-label*="connect" i]:not([aria-label*="disconnect"]), '
                'main button:has-text("Connect")'
            )
            if connect_btn and connect_btn.is_visible():
                # Make sure it's actually the Connect button and not something else
                text = connect_btn.inner_text().strip()
                if "Connect" in text and "Disconnect" not in text:
                    return "connect_visible"
        except Exception:
            pass

        # Check if "Connect" is inside the "More" dropdown
        try:
            more_btn = page.query_selector(
                'button[aria-label="More actions"], '
                'button.pvs-profile-actions__overflow-toggle, '
                'button:has-text("More")'
            )
            if more_btn and more_btn.is_visible():
                more_btn.click()
                self._random_delay((1, 2))

                connect_in_dropdown = page.query_selector(
                    'div[data-test-dropdown] span:has-text("Connect"), '
                    '.artdeco-dropdown__content span:has-text("Connect"), '
                    '[role="listbox"] span:has-text("Connect"), '
                    'li span:has-text("Connect")'
                )
                if connect_in_dropdown and connect_in_dropdown.is_visible():
                    # Close the dropdown first (we'll reopen when clicking)
                    page.keyboard.press("Escape")
                    self._random_delay((0.5, 1))
                    return "connect_in_more"

                # Check if "Message" is prominent (already connected)
                message_in_dropdown = page.query_selector(
                    'span:has-text("Message")'
                )
                # Close dropdown
                page.keyboard.press("Escape")
                self._random_delay((0.5, 1))
        except Exception:
            pass

        # Check for prominent "Message" button (means already connected)
        try:
            message_btn = page.query_selector(
                'button.pvs-profile-actions__action:has-text("Message"), '
                'a:has-text("Message")'
            )
            if message_btn and message_btn.is_visible():
                return "already_connected"
        except Exception:
            pass

        return "no_connect_button"

    def _click_connect_button(self, state: str) -> bool:
        """
        Click the Connect button based on detected state.

        Args:
            state: "connect_visible" or "connect_in_more"

        Returns:
            True if successfully clicked, False otherwise.
        """
        page = self.page

        if state == "connect_visible":
            try:
                connect_btn = page.query_selector(
                    'button.pvs-profile-actions__action:has-text("Connect"), '
                    'button[aria-label*="connect" i]:not([aria-label*="disconnect"]), '
                    'main button:has-text("Connect")'
                )
                if connect_btn and connect_btn.is_visible():
                    connect_btn.click()
                    return True
            except Exception as e:
                print(f"[BOT]   Error clicking Connect button: {e}")
                return False

        elif state == "connect_in_more":
            try:
                # Open the More dropdown
                more_btn = page.query_selector(
                    'button[aria-label="More actions"], '
                    'button.pvs-profile-actions__overflow-toggle, '
                    'button:has-text("More")'
                )
                if more_btn:
                    more_btn.click()
                    self._random_delay((1, 2))

                    # Click Connect in the dropdown
                    connect_item = page.query_selector(
                        'div[data-test-dropdown] span:has-text("Connect"), '
                        '.artdeco-dropdown__content span:has-text("Connect"), '
                        '[role="listbox"] span:has-text("Connect"), '
                        'li span:has-text("Connect")'
                    )
                    if connect_item:
                        connect_item.click()
                        return True
            except Exception as e:
                print(f"[BOT]   Error clicking Connect in More dropdown: {e}")
                return False

        return False

    def _handle_connection_modal(self, note: str) -> bool:
        """
        Handle the connection request modal: optionally add a note and send.

        After clicking "Connect", LinkedIn may show:
            1. A modal asking "How do you know [name]?" → click "Other" then "Connect"
            2. A modal with "Add a note" option → click it, type note, click "Send"
            3. Directly a send button

        Args:
            note: The personalized connection note to include.

        Returns:
            True if the request was sent successfully, False otherwise.
        """
        page = self.page
        self._random_delay((1, 3))

        try:
            # Check for LinkedIn's weekly cap warning
            cap_warning = page.query_selector(
                'div:has-text("You\'ve reached the weekly invitation limit"), '
                'div:has-text("weekly invitation limit")'
            )
            if cap_warning and cap_warning.is_visible():
                raise LinkedInCapReachedError("Weekly invitation limit reached")
        except LinkedInCapReachedError:
            raise
        except Exception:
            pass

        # Try to find "Add a note" button
        try:
            add_note_btn = page.query_selector(
                'button[aria-label="Add a note"], '
                'button:has-text("Add a note")'
            )
            if add_note_btn and add_note_btn.is_visible():
                add_note_btn.click()
                self._random_delay((1, 2))

                # Type the note in the textarea
                note_field = page.wait_for_selector(
                    'textarea[name="message"], '
                    'textarea#custom-message, '
                    'textarea.connect-button-send-invite__custom-message, '
                    '.artdeco-modal textarea, '
                    'textarea',
                    timeout=5000,
                )
                if note_field:
                    note_field.fill("")  # Clear any existing text
                    self._random_delay((0.5, 1))
                    # Type character-by-character for human-like input
                    note_field.type(note, delay=random.randint(30, 80))
                    self._random_delay((1, 2))

                    # Click "Send" / "Send invitation"
                    return self._click_send_button()
        except Exception as e:
            print(f"[BOT]   Error adding note: {e}")

        # If "Add a note" wasn't found, try handling "How do you know" modal
        try:
            other_option = page.query_selector(
                'label:has-text("Other"), '
                'button:has-text("Other")'
            )
            if other_option and other_option.is_visible():
                other_option.click()
                self._random_delay((1, 2))

                # Now look for "Connect" or "Send" button
                return self._click_send_button()
        except Exception:
            pass

        # Last resort: try directly clicking Send
        return self._click_send_button()

    def _click_send_button(self) -> bool:
        """
        Find and click the Send / Send invitation button in a modal.

        Returns:
            True if clicked successfully, False otherwise.
        """
        page = self.page
        self._random_delay((0.5, 1.5))

        send_selectors = [
            'button[aria-label="Send invitation"]',
            'button[aria-label="Send now"]',
            'button:has-text("Send invitation")',
            'button:has-text("Send")',
            '.artdeco-modal button.artdeco-button--primary',
        ]

        for selector in send_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    self._random_delay((1, 3))

                    # Verify the modal closed (request sent successfully)
                    try:
                        page.wait_for_selector('.artdeco-modal', state='hidden', timeout=5000)
                    except Exception:
                        pass  # Modal may have already closed

                    return True
            except Exception:
                continue

        print("[BOT]   Could not find Send button")
        return False

    # ─── Dry Run ─────────────────────────────────────────────────────────────

    def dry_run_connection(self, url: str, note_template: Optional[str] = None) -> str:
        """
        Visit a profile and simulate a connection request without clicking.
        Useful for testing and verifying the tool works before going live.

        Args:
            url: LinkedIn profile URL.
            note_template: Message template with {first_name} placeholder.

        Returns:
            Status string describing what WOULD happen.
        """
        if note_template is None:
            note_template = get_connection_note_template()

        try:
            profile_info = self.visit_profile(url)
            first_name = profile_info["first_name"]
            personalized_note = note_template.format(first_name=first_name)
            if len(personalized_note) > 300:
                personalized_note = personalized_note[:297] + "..."

            state = self._detect_connection_state()

            print(f"[DRY RUN] Profile: {profile_info['name']}")
            print(f"[DRY RUN] State: {state}")
            print(f"[DRY RUN] Note: {personalized_note}")

            if state in ("connect_visible", "connect_in_more"):
                return STATUS_REQUEST_SENT  # Would send
            elif state == "already_connected":
                return "already_connected"
            elif state == "already_pending":
                return "already_pending"
            else:
                return STATUS_SKIPPED

        except ProfileNotFoundError:
            print(f"[DRY RUN] Profile not found (404)")
            return STATUS_ERROR
        except SessionExpiredError:
            print(f"[DRY RUN] Session expired")
            return STATUS_ERROR
        except Exception as e:
            print(f"[DRY RUN] Error: {e}")
            return STATUS_ERROR


# ─── Custom Exceptions ───────────────────────────────────────────────────────


class ProfileNotFoundError(Exception):
    """Raised when a LinkedIn profile URL leads to a 404 page."""
    pass


class SessionExpiredError(Exception):
    """Raised when the browser session has expired and user needs to re-login."""
    pass


class LinkedInCapReachedError(Exception):
    """Raised when LinkedIn's weekly invitation limit has been reached."""
    pass
