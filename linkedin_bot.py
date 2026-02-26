"""
linkedin_bot.py — Playwright-based LinkedIn browser automation.

Handles:
    - Browser launch with anti-detection settings
    - Manual login with session persistence (cookies saved to state.json)
    - Session restoration across runs (no repeated logins)
    - Profile visiting & name extraction
    - Connection request sending with personalized notes
    - Follow-up messaging to accepted connections
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
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_MESSAGED,
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
    STATUS_SKIPPED,
    USER_AGENT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    get_connection_note_template,
    get_followup_message_template,
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

        # Launch Chromium with anti-detection args + Docker-safe + low-memory flags
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--no-first-run",
                "--disable-setuid-sandbox",
                "--disable-accelerated-2d-canvas",
                "--no-zygote",
                # Memory reduction flags
                "--js-flags=--max-old-space-size=256",
                "--disable-features=TranslateUI",
                "--disable-features=BlinkGenPropertyTrees",
                "--disable-ipc-flooding-protection",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-hang-monitor",
                "--disable-prompt-on-repost",
                "--disable-domain-reliability",
                "--metrics-recording-only",
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

    def send_connection_request(self, url: str, note_template: Optional[str] = None, send_note: bool = True) -> str:
        """
        Visit a profile and send a connection request.

        Args:
            url: LinkedIn profile URL.
            note_template: Message template with {first_name} placeholder.
                          If None, loads from templates/connection_note.txt.
            send_note: If True, send with a personalized note.
                      If False, send without a note ("Send without a note").

        Returns:
            Status string: "request_sent", "already_pending", "already_connected",
                          "skipped", "error", "cap_reached"
        """
        if send_note and note_template is None:
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
            full_name = profile_info["name"]

            # Step 2: Detect the current connection state
            state = self._detect_connection_state(full_name)
            print(f"[BOT]   Connection state: {state}")

            if state == "already_connected":
                return "already_connected"
            elif state == "already_pending":
                return "already_pending"
            elif state == "no_connect_button":
                print(f"[BOT]   No Connect button found (Follow-only or restricted profile)")
                return STATUS_SKIPPED

            # Step 3: Click Connect (may be behind "More" dropdown)
            clicked = self._click_connect_button(state, full_name)
            if not clicked:
                print("[BOT]   Failed to click Connect button")
                return STATUS_ERROR

            self.action_delay()

            # Step 4: Handle the connection modal
            if send_note and note_template:
                personalized_note = note_template.format(first_name=first_name)
                # LinkedIn limits notes to 300 characters
                if len(personalized_note) > 300:
                    personalized_note = personalized_note[:297] + "..."
                    print(f"[BOT]   Note truncated to 300 chars")
                sent = self._handle_connection_modal(personalized_note)
            else:
                # Send without a note (Codegen-proven flow)
                sent = self._send_without_note()

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

    def _send_without_note(self) -> bool:
        """
        Click 'Send without a note' in the connection modal.

        Exact selector from Playwright Codegen:
            page.get_by_role("button", name="Send without a note").click()

        Returns:
            True if successfully clicked, False otherwise.
        """
        page = self.page
        self._random_delay((1, 3))

        # Check for LinkedIn's weekly cap warning first
        try:
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

        # Primary: use get_by_role from Codegen
        try:
            send_btn = page.get_by_role("button", name="Send without a note")
            if send_btn.is_visible():
                print("[BOT]   Clicking 'Send without a note'")
                send_btn.click()
                self._random_delay((1, 3))
                # Verify modal closed
                try:
                    page.wait_for_selector(
                        '.artdeco-modal, [role="dialog"]',
                        state='hidden',
                        timeout=5000,
                    )
                except Exception:
                    pass
                return True
        except Exception as e:
            print(f"[BOT]   'Send without a note' button not found: {e}")

        # Fallback: try CSS selectors
        fallback_selectors = [
            'button[aria-label="Send without a note"]',
            'button:has-text("Send without a note")',
            '.artdeco-modal button.artdeco-button--secondary',
        ]
        for sel in fallback_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    text = btn.inner_text().strip()
                    print(f"[BOT]   Clicking fallback send button: '{text}'")
                    btn.click()
                    self._random_delay((1, 3))
                    return True
            except Exception:
                continue

        # Last resort: try "Send invitation" (some modals only show this)
        try:
            send_inv = page.get_by_role("button", name="Send invitation")
            if send_inv.is_visible():
                print("[BOT]   Falling back to 'Send invitation'")
                send_inv.click()
                self._random_delay((1, 3))
                return True
        except Exception:
            pass

        print("[BOT]   Could not find any send button")
        return False

    def _detect_connection_state(self, name: str = "") -> str:
        """
        Detect the current connection state with this profile.

        Uses Playwright's get_by_role() with the accessible name pattern
        "Invite {name} to" which is how LinkedIn labels the Connect button.

        Args:
            name: The profile person's full name (e.g. "Sriraj Behera").

        Returns:
            "connect_visible"   — Connect/Invite button is directly visible
            "connect_in_more"   — Connect is hidden in the "More" dropdown
            "already_pending"   — Invitation already sent (Pending)
            "already_connected" — Already connected (Message button is primary/blue)
            "no_connect_button" — No connect option found at all
        """
        page = self.page

        ACTION_BAR = (
            ".pvs-profile-actions, "
            ".pv-top-card-v2-ctas, "
            "div.ph5 .pvs-profile-actions, "
            ".pv-top-card .pv-top-card-v2-ctas"
        )

        # ── Debug: log the primary action buttons we see ──
        try:
            btns = page.query_selector_all(f"{ACTION_BAR} button")
            visible_labels = []
            for btn in btns:
                try:
                    if btn.is_visible():
                        text = btn.inner_text().strip().replace("\n", " ")
                        aria = btn.get_attribute("aria-label") or ""
                        if text or aria:
                            visible_labels.append(f"{text} [aria={aria}]")
                except Exception:
                    pass
            if visible_labels:
                print(f"[BOT]   Profile action buttons: {visible_labels}")
        except Exception:
            pass

        # ── 1. Check for "Pending" state ──
        try:
            pending_btn = page.get_by_role("button", name="Pending")
            if pending_btn.is_visible():
                return "already_pending"
        except Exception:
            pass

        # ── 2. Check for "Invite {name} to" / "Invite {name} to connect" button ──
        # LinkedIn uses two variants:
        #   - Direct Connect button: "Invite {name} to"
        #   - More dropdown Connect: "Invite {name} to connect"
        if name:
            for variant in [f"Invite {name} to connect", f"Invite {name} to"]:
                try:
                    invite_btn = page.get_by_role("button", name=variant)
                    if invite_btn.is_visible():
                        return "connect_visible"
                except Exception:
                    pass

        # ── 3. Fallback: check any button with aria-label containing "Invite" ──
        try:
            btns = page.query_selector_all(f"{ACTION_BAR} button")
            for btn in btns:
                try:
                    if btn.is_visible():
                        aria = (btn.get_attribute("aria-label") or "")
                        if "Invite" in aria and " to" in aria:
                            return "connect_visible"
                except Exception:
                    continue
        except Exception:
            pass

        # ── 4. Check for FILLED BLUE "Message" button (primary = connected) ──
        try:
            msg_btn = page.query_selector(
                f'{ACTION_BAR} button.artdeco-button--primary:has-text("Message")'
            )
            if msg_btn and msg_btn.is_visible():
                return "already_connected"
        except Exception:
            pass

        # ── 5. Check "More" dropdown for Connect ──
        try:
            found_in_more = self._check_more_dropdown_for_connect(name)
            if found_in_more:
                return "connect_in_more"
        except Exception:
            pass

        return "no_connect_button"

    def _check_more_dropdown_for_connect(self, name: str = "") -> bool:
        """
        Open the 'More' dropdown on a profile and check if 'Connect' is listed.
        Closes the dropdown before returning.

        Args:
            name: Full name of the profile person.

        Returns:
            True if Connect was found in the More dropdown.
        """
        page = self.page
        try:
            # Use exact selector from Codegen
            more_btn = page.get_by_role("button", name="More actions")
            if not more_btn.is_visible():
                return False

            more_btn.click()
            self._random_delay((1, 2))

            # Debug: log all items visible in the dropdown
            try:
                dropdown_items = page.query_selector_all(
                    '.artdeco-dropdown__content li, '
                    '.artdeco-dropdown__content-inner li, '
                    '.artdeco-dropdown__content .artdeco-dropdown__item'
                )
                visible_items = []
                for item in dropdown_items:
                    try:
                        if item.is_visible():
                            text = item.inner_text().strip().replace("\n", " ")
                            aria = ""
                            try:
                                btn = item.query_selector("button, a, div[role='button']")
                                if btn:
                                    aria = btn.get_attribute("aria-label") or ""
                            except Exception:
                                pass
                            if text or aria:
                                visible_items.append(f"{text} [aria={aria}]")
                    except Exception:
                        pass
                if visible_items:
                    print(f"[BOT]   More dropdown items: {visible_items}")
            except Exception:
                pass

            # Check for "Invite {name} to connect" / "Invite {name} to" in dropdown
            if name:
                for variant in [f"Invite {name} to connect", f"Invite {name} to"]:
                    try:
                        invite_item = page.get_by_role("button", name=variant)
                        if invite_item.is_visible():
                            page.keyboard.press("Escape")
                            self._random_delay((0.5, 1))
                            return True
                    except Exception:
                        pass

            # Fallback: look for any element with aria-label containing "Invite"
            try:
                items = page.query_selector_all(
                    '.artdeco-dropdown__content [aria-label*="Invite"], '
                    '.artdeco-dropdown__content span:has-text("Connect"), '
                    '.artdeco-dropdown__content div:has-text("Connect")'
                )
                for item in items:
                    try:
                        if item.is_visible():
                            page.keyboard.press("Escape")
                            self._random_delay((0.5, 1))
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            # Close the dropdown
            page.keyboard.press("Escape")
            self._random_delay((0.5, 1))

            return False
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _click_connect_button(self, state: str, name: str = "") -> bool:
        """
        Click the Connect button based on detected state.

        Uses Playwright get_by_role with "Invite {name} to" accessible name
        (the actual label LinkedIn gives the Connect button).

        Args:
            state: "connect_visible" or "connect_in_more"
            name: Full name of the profile person.

        Returns:
            True if successfully clicked, False otherwise.
        """
        page = self.page

        if state == "connect_visible":
            try:
                # Primary: use get_by_role with both name variants (from Codegen)
                if name:
                    for variant in [f"Invite {name} to connect", f"Invite {name} to"]:
                        try:
                            invite_btn = page.get_by_role("button", name=variant)
                            if invite_btn.is_visible():
                                print(f"[BOT]   Clicking '{variant}' button")
                                invite_btn.click()
                                return True
                        except Exception:
                            continue

                # Fallback: find button by aria-label containing "Invite"
                ACTION_BAR = ".pvs-profile-actions, .pv-top-card-v2-ctas"
                btns = page.query_selector_all(f"{ACTION_BAR} button")
                for btn in btns:
                    try:
                        if btn.is_visible():
                            aria = btn.get_attribute("aria-label") or ""
                            if "Invite" in aria and " to" in aria:
                                print(f"[BOT]   Clicking button [aria-label='{aria}']")
                                btn.click()
                                return True
                    except Exception:
                        continue

            except Exception as e:
                print(f"[BOT]   Error clicking Connect button: {e}")
                return False

        elif state == "connect_in_more":
            try:
                # Open the More dropdown (exact selector from Codegen)
                more_btn = page.get_by_role("button", name="More actions")
                if more_btn.is_visible():
                    print(f"[BOT]   Opening 'More actions' dropdown")
                    more_btn.click()
                    self._random_delay((1, 2))

                    # Primary: try both Codegen name variants
                    if name:
                        for variant in [f"Invite {name} to connect", f"Invite {name} to"]:
                            try:
                                invite_item = page.get_by_role("button", name=variant)
                                if invite_item.is_visible():
                                    print(f"[BOT]   Clicking '{variant}' in dropdown")
                                    invite_item.click()
                                    return True
                            except Exception:
                                continue

                    # Fallback: find by aria-label or text
                    items = page.query_selector_all(
                        '.artdeco-dropdown__content [aria-label*="Invite"], '
                        '.artdeco-dropdown__content span:has-text("Connect"), '
                        'li:has-text("Connect")'
                    )
                    for item in items:
                        try:
                            if item.is_visible():
                                print(f"[BOT]   Clicking Connect in dropdown (fallback)")
                                item.click()
                                return True
                        except Exception:
                            continue

                    print("[BOT]   Connect not found in More dropdown")
                    page.keyboard.press("Escape")
            except Exception as e:
                print(f"[BOT]   Error clicking Connect in More dropdown: {e}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

        return False

    def _handle_connection_modal(self, note: str) -> bool:
        """
        Handle the connection request modal: add a note and send.

        Uses exact selectors from Playwright Codegen:
        1. Click "Add a note" button
        2. Fill the note textbox ("Please limit personal note to")
        3. Click "Send invitation"

        Args:
            note: The personalized connection note to include.

        Returns:
            True if the request was sent successfully, False otherwise.
        """
        page = self.page

        # Wait for a modal / overlay to appear
        try:
            page.wait_for_selector(
                '.artdeco-modal, [role="dialog"], .send-invite',
                timeout=5000,
            )
        except Exception:
            print("[BOT]   No modal appeared after clicking Connect")
        self._random_delay((1, 3))

        # ── Debug: log all visible buttons in the modal ──
        try:
            modal_buttons = page.query_selector_all(
                '.artdeco-modal button, [role="dialog"] button'
            )
            visible_labels = []
            for btn in modal_buttons:
                try:
                    if btn.is_visible():
                        label = btn.inner_text().strip().replace("\n", " ")
                        aria = btn.get_attribute("aria-label") or ""
                        visible_labels.append(f"{label} (aria={aria})")
                except Exception:
                    pass
            if visible_labels:
                print(f"[BOT]   Modal buttons found: {visible_labels}")
        except Exception:
            pass

        # ── Check for LinkedIn's weekly cap warning ──
        try:
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

        # ── Strategy 1: "Add a note" → fill textbox → "Send invitation" ──
        # (Exact flow from Playwright Codegen)
        try:
            add_note_btn = page.get_by_role("button", name="Add a note")
            if add_note_btn.is_visible():
                add_note_btn.click()
                print("[BOT]   Clicked 'Add a note'")
                self._random_delay((1, 2))

                # Fill the note textbox
                textbox = page.get_by_role("textbox", name="Please limit personal note to")
                textbox.fill(note)
                print(f"[BOT]   Typed note ({len(note)} chars)")
                self._random_delay((1, 2))

                # Click Send invitation
                send_btn = page.get_by_role("button", name="Send invitation")
                send_btn.click()
                print("[BOT]   Clicked 'Send invitation'")
                self._random_delay((1, 3))

                # Verify modal closed
                try:
                    page.wait_for_selector(
                        '.artdeco-modal, [role="dialog"]',
                        state='hidden',
                        timeout=5000,
                    )
                except Exception:
                    pass
                return True
        except Exception as e:
            print(f"[BOT]   Strategy 1 (Add a note) failed: {e}")

        # ── Strategy 2: Textarea already visible (no "Add a note" step) ──
        try:
            textbox = page.get_by_role("textbox", name="Please limit personal note to")
            if textbox.is_visible():
                print("[BOT]   Textarea already visible, typing note...")
                textbox.fill(note)
                print(f"[BOT]   Typed note ({len(note)} chars)")
                self._random_delay((1, 2))
                send_btn = page.get_by_role("button", name="Send invitation")
                send_btn.click()
                print("[BOT]   Clicked 'Send invitation'")
                self._random_delay((1, 3))
                return True
        except Exception:
            pass

        # ── Strategy 3: "How do you know" modal → click "Other" → proceed ──
        try:
            other_selectors = [
                'label:has-text("Other")',
                'button:has-text("Other")',
                '.artdeco-modal label:has-text("Other")',
            ]
            for sel in other_selectors:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    print("[BOT]   Clicked 'Other' option")
                    self._random_delay((1, 2))
                    return self._click_send_button()
        except Exception:
            pass

        # ── Strategy 4: "Send without a note" fallback ──
        try:
            send_without = page.get_by_role("button", name="Send without a note")
            if send_without.is_visible():
                print("[BOT]   Sending without a note (no note option available)")
                send_without.click()
                self._random_delay((1, 3))
                return True
        except Exception:
            pass

        # ── Strategy 5: Try clicking Send invitation directly ──
        return self._click_send_button()

    def _type_note_and_send(self, note: str) -> bool:
        """
        Type a note into the modal's textarea and click Send.

        Uses Playwright get_by_role selectors from Codegen.

        Args:
            note: The personalized connection note text.

        Returns:
            True if sent successfully, False otherwise.
        """
        page = self.page

        try:
            # Primary: use get_by_role (from Codegen)
            textbox = page.get_by_role("textbox", name="Please limit personal note to")
            if textbox.is_visible():
                textbox.fill(note)
                self._random_delay((1, 2))
                print(f"[BOT]   Typed note ({len(note)} chars)")
                return self._click_send_button()
        except Exception:
            pass

        # Fallback: find textarea by CSS
        try:
            textarea_selectors = [
                '.artdeco-modal textarea',
                '[role="dialog"] textarea',
                'textarea[name="message"]',
                'textarea',
            ]

            for sel in textarea_selectors:
                try:
                    field = page.wait_for_selector(sel, timeout=3000)
                    if field and field.is_visible():
                        field.fill(note)
                        self._random_delay((1, 2))
                        print(f"[BOT]   Typed note ({len(note)} chars) (fallback selector)")
                        return self._click_send_button()
                except Exception:
                    continue

            print("[BOT]   Could not find note textarea")
            return self._click_send_button()

        except Exception as e:
            print(f"[BOT]   Error typing note: {e}")
            return self._click_send_button()

    def _click_send_button(self) -> bool:
        """
        Find and click the Send / Send invitation button in a modal.

        Primary selector from Playwright Codegen:
            get_by_role("button", name="Send invitation")

        Returns:
            True if clicked successfully, False otherwise.
        """
        page = self.page
        self._random_delay((0.5, 1.5))

        # Primary: use get_by_role (from Codegen)
        try:
            send_btn = page.get_by_role("button", name="Send invitation")
            if send_btn.is_visible():
                print("[BOT]   Clicking 'Send invitation'")
                send_btn.click()
                self._random_delay((1, 3))
                try:
                    page.wait_for_selector(
                        '.artdeco-modal, [role="dialog"]',
                        state='hidden',
                        timeout=5000,
                    )
                except Exception:
                    pass
                return True
        except Exception:
            pass

        # Fallback selectors
        send_selectors = [
            'button[aria-label="Send invitation"]',
            'button[aria-label="Send now"]',
            'button:has-text("Send invitation")',
            'button:has-text("Send now")',
            '.artdeco-modal button.artdeco-button--primary',
            '[role="dialog"] button.artdeco-button--primary',
            '.artdeco-modal button:has-text("Send")',
            '[role="dialog"] button:has-text("Send")',
        ]

        for selector in send_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible() and btn.is_enabled():
                    text = btn.inner_text().strip()
                    print(f"[BOT]   Clicking send button: '{text}'")
                    btn.click()
                    self._random_delay((1, 3))
                    try:
                        page.wait_for_selector(
                            '.artdeco-modal, [role="dialog"]',
                            state='hidden',
                            timeout=5000,
                        )
                    except Exception:
                        pass
                    return True
            except Exception:
                continue

        # Debug: log visible buttons
        try:
            all_buttons = page.query_selector_all("button")
            visible = []
            for b in all_buttons:
                try:
                    if b.is_visible():
                        visible.append(b.inner_text().strip()[:40])
                except Exception:
                    pass
            print(f"[BOT]   Could not find Send button. Visible buttons: {visible[:15]}")
        except Exception:
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

            state = self._detect_connection_state(profile_info['name'])

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


    # ─── Follow-Up Messaging ─────────────────────────────────────────────────

    def check_connection_status(self, url: str) -> str:
        """
        Visit a profile and check if the connection has been accepted.

        Args:
            url: LinkedIn profile URL.

        Returns:
            "connected"     — Message button present (accepted)
            "pending"       — Still pending
            "not_connected" — No connection relationship
            "error"         — Could not determine
        """
        try:
            profile_info = self.visit_profile(url)
            state = self._detect_connection_state(profile_info['name'])

            if state == "already_connected":
                return "connected"
            elif state == "already_pending":
                return "pending"
            elif state in ("connect_visible", "connect_in_more"):
                return "not_connected"
            else:
                return "not_connected"

        except ProfileNotFoundError:
            return "error"
        except SessionExpiredError:
            return "error"
        except Exception:
            return "error"

    def send_followup_message(self, url: str, message_template: Optional[str] = None) -> str:
        """
        Visit a profile and send a follow-up message if connected.

        Uses Codegen-proven selectors:
            1. get_by_role("button", name="Message {first_name}").click()
            2. get_by_role("textbox", name="Write a message…").fill(msg)
            3. get_by_role("button", name="Send", exact=True).click()
            4. get_by_role("button", name="Close your conversation with").click()

        Args:
            url: LinkedIn profile URL.
            message_template: Message with {first_name} placeholder.
                             If None, loads from templates/followup_message.txt.

        Returns:
            Status string: "messaged", "not_connected", "skipped", "error"
        """
        if message_template is None:
            message_template = get_followup_message_template()

        try:
            # Step 1: Visit the profile
            profile_info = self.visit_profile(url)
            first_name = profile_info["first_name"]
            full_name = profile_info["name"]
            print(f"[BOT]   Name: {full_name}")

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
            page = self.page

            # Step 2: Click Message button using Codegen selector
            # Pattern: "Message {first_name}"
            message_btn = page.get_by_role("button", name=f"Message {first_name}")
            try:
                if not message_btn.is_visible(timeout=3000):
                    print(f"[BOT]   No 'Message {first_name}' button found — not connected")
                    return "not_connected"
            except Exception:
                print(f"[BOT]   No 'Message {first_name}' button found — not connected")
                return "not_connected"

            print(f"[BOT]   Clicking 'Message {first_name}'")
            message_btn.click()
            self._random_delay((2, 4))

            # Step 3: Fill the message textbox
            personalized_msg = message_template.format(first_name=first_name)
            try:
                textbox = page.get_by_role("textbox", name="Write a message\u2026")
                textbox.click()
                self._random_delay((0.5, 1))
                textbox.fill(personalized_msg)
                print(f"[BOT]   Typed message ({len(personalized_msg)} chars)")
                self._random_delay((1, 2))
            except Exception as e:
                print(f"[BOT]   Could not fill message textbox: {e}")
                self._close_chat_modal(first_name)
                return STATUS_ERROR

            # Step 4: Click Send
            try:
                send_btn = page.get_by_role("button", name="Send", exact=True)
                send_btn.click()
                print(f"[BOT]   Clicked 'Send'")
                self._random_delay((1, 3))
            except Exception as e:
                print(f"[BOT]   Could not click Send button: {e}")
                self._close_chat_modal(first_name)
                return STATUS_ERROR

            # Step 5: Close the chat
            self._close_chat_modal(first_name)
            print(f"[BOT]   ✓ Follow-up message sent!")
            return STATUS_MESSAGED

        except Exception as e:
            print(f"[BOT]   Error sending message: {e}")
            self._close_chat_modal(first_name)
            return STATUS_ERROR

    def _close_chat_modal(self, first_name: str = ""):
        """
        Close the chat/messaging overlay.

        Uses Codegen selector:
            get_by_role("button", name="Close your conversation with")
        """
        page = self.page
        try:
            close_btn = page.get_by_role("button", name="Close your conversation with")
            if close_btn.is_visible():
                close_btn.click()
                self._random_delay((0.5, 1))
                return
        except Exception:
            pass

        # Fallback: press Escape
        try:
            page.keyboard.press("Escape")
            self._random_delay((0.5, 1))
        except Exception:
            pass

    def dry_run_message(self, url: str, message_template: Optional[str] = None) -> str:
        """
        Visit a profile and simulate sending a follow-up message without clicking.

        Args:
            url: LinkedIn profile URL.
            message_template: Message with {first_name} placeholder.

        Returns:
            Status string describing what WOULD happen.
        """
        if message_template is None:
            message_template = get_followup_message_template()

        try:
            profile_info = self.visit_profile(url)
            first_name = profile_info["first_name"]
            personalized_msg = message_template.format(first_name=first_name)

            # Check if Message button is available using Codegen selector
            page = self.page
            message_btn = page.get_by_role("button", name=f"Message {first_name}")
            btn_visible = False
            try:
                btn_visible = message_btn.is_visible(timeout=3000)
            except Exception:
                pass

            print(f"[DRY RUN] Profile: {profile_info['name']}")
            print(f"[DRY RUN] Message button found: {btn_visible}")
            print(f"[DRY RUN] Message: {personalized_msg[:100]}...")

            if btn_visible:
                return STATUS_MESSAGED  # Would send
            else:
                return "not_connected"

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
