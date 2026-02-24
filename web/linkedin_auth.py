"""
linkedin_auth.py — Playwright-based LinkedIn login for the web app.

Handles:
    1. Email + password login
    2. Detection of verification/2FA prompts
    3. Verification code submission
    4. Session extraction (storage_state JSON)
"""

import base64
import json
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright


# LinkedIn URLs
LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"
CHECKPOINT_URL = "checkpoint"

# Stealth JS to avoid detection
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


def login_to_linkedin(email: str, password: str) -> dict:
    """
    Attempt to log into LinkedIn with email and password.

    Returns a dict with:
        - success: bool
        - needs_verification: bool (2FA / email code required)
        - session_json: str (JSON storage state, only on success)
        - error: str (error message, only on failure)
        - browser_state: bytes (pickled browser for verification step)
    """
    pw = None
    browser = None
    context = None

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-zygote",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.add_init_script(STEALTH_JS)

        # Navigate to login
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        # Enter email
        email_field = page.locator('#username, input[name="session_key"]')
        email_field.fill(email)
        time.sleep(0.5)

        # Enter password
        pass_field = page.locator('#password, input[name="session_password"]')
        pass_field.fill(password)
        time.sleep(0.5)

        # Click Sign in
        sign_in_btn = page.locator('button[type="submit"][data-litms-control-urn*="login-submit"]')
        if sign_in_btn.count() == 0:
            sign_in_btn = page.locator('form#organic-div button[type="submit"]')
        if sign_in_btn.count() == 0:
            sign_in_btn = page.get_by_role("button", name="Sign in").first
        sign_in_btn.first.click()
        time.sleep(5)  # Wait for redirect

        current_url = page.url

        # Check: successful login → feed
        if "/feed" in current_url or "/mynetwork" in current_url:
            session_data = context.storage_state()
            session_json = json.dumps(session_data, indent=2)
            return {
                "success": True,
                "needs_verification": False,
                "session_json": session_json,
                "error": None,
            }

        # Check: verification / checkpoint required
        if (
            CHECKPOINT_URL in current_url
            or "challenge" in current_url
            or "two-step-verification" in current_url
        ):
            # Capture what LinkedIn is actually showing
            page_text = ""
            screenshot_b64 = ""
            try:
                page_text = page.inner_text("body")[:500]
                screenshot_bytes = page.screenshot()
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception:
                pass

            print(f"[AUTH] Challenge page detected: {current_url}")
            print(f"[AUTH] Page text: {page_text[:200]}")

            # Save the intermediate state so we can continue after code entry
            intermediate_state = json.dumps(context.storage_state(), indent=2)
            return {
                "success": False,
                "needs_verification": True,
                "session_json": None,
                "intermediate_state": intermediate_state,
                "verification_url": current_url,
                "page_text": page_text,
                "screenshot_b64": screenshot_b64,
                "error": None,
            }

        # Check: wrong credentials
        error_el = page.locator(
            '#error-for-password, '
            '.form__label--error, '
            'div[role="alert"], '
            '#error-for-username'
        )
        try:
            if error_el.first.is_visible():
                error_text = error_el.first.inner_text().strip()
                return {
                    "success": False,
                    "needs_verification": False,
                    "session_json": None,
                    "error": error_text or "Invalid email or password.",
                }
        except Exception:
            pass

        # Unknown state
        return {
            "success": False,
            "needs_verification": False,
            "session_json": None,
            "error": f"Login failed. Ended up at: {current_url[:100]}",
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "success": False,
            "needs_verification": False,
            "session_json": None,
            "error": str(e)[:300],
        }
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
            if pw:
                pw.stop()
        except Exception:
            pass


def submit_verification_code(intermediate_state: str, code: str) -> dict:
    """
    Continue LinkedIn login by submitting a verification code.

    Args:
        intermediate_state: JSON storage state from the initial login attempt.
        code: The verification code sent to user's email/phone.

    Returns:
        Same dict format as login_to_linkedin().
    """
    pw = None
    browser = None
    context = None

    try:
        state_data = json.loads(intermediate_state)

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-zygote",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context(
            storage_state=state_data,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.add_init_script(STEALTH_JS)

        # Go to feed (will redirect to checkpoint if needed)
        page.goto(FEED_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        current_url = page.url

        # If we're already on the feed, session was enough
        if "/feed" in current_url:
            session_data = context.storage_state()
            return {
                "success": True,
                "needs_verification": False,
                "session_json": json.dumps(session_data, indent=2),
                "error": None,
            }

        # Find and fill the verification code input
        code_input = page.locator(
            'input[name="pin"], '
            'input#input__email_verification_pin, '
            'input[name="verificationCode"], '
            'input[type="text"][name*="pin"], '
            'input[type="text"][name*="code"], '
            'input[type="tel"], '
            'input.input_verification_pin'
        )

        try:
            code_input.first.fill(code)
            time.sleep(1)
        except Exception:
            return {
                "success": False,
                "needs_verification": True,
                "session_json": None,
                "error": "Could not find the verification code input field.",
            }

        # Click submit / verify button
        submit_btn = page.locator(
            'button[type="submit"], '
            'button:has-text("Submit"), '
            'button:has-text("Verify"), '
            'button#two-step-submit-button'
        )
        try:
            submit_btn.first.click()
            time.sleep(5)
        except Exception:
            # Try pressing Enter as fallback
            page.keyboard.press("Enter")
            time.sleep(5)

        current_url = page.url

        # Check if we made it to the feed
        if "/feed" in current_url or "/mynetwork" in current_url:
            session_data = context.storage_state()
            return {
                "success": True,
                "needs_verification": False,
                "session_json": json.dumps(session_data, indent=2),
                "error": None,
            }

        # Still on checkpoint → wrong code or another challenge
        if CHECKPOINT_URL in current_url or "challenge" in current_url:
            return {
                "success": False,
                "needs_verification": True,
                "session_json": None,
                "error": "Verification failed. Please check the code and try again.",
            }

        return {
            "success": False,
            "needs_verification": False,
            "session_json": None,
            "error": f"Verification completed but login failed. URL: {current_url[:100]}",
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "success": False,
            "needs_verification": False,
            "session_json": None,
            "error": str(e)[:300],
        }
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
            if pw:
                pw.stop()
        except Exception:
            pass
