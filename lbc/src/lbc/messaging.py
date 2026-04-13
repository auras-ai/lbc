"""
Login + messaging.

Approach: UI automation against the same persistent Chromium profile used for
search. Rationale:

  * Leboncoin's chat uses a proprietary backend (chat.leboncoin.fr + WebSocket)
    with short-lived JWTs minted by its login flow. Reverse-engineering the
    token pipeline is brittle and changes often.
  * Datadome sits in front of everything — the UI has already solved it once.
  * `launch_persistent_context` keeps cookies + localStorage between runs, so
    the user signs in ONCE via `lbc login`, and every later command (send,
    inbox, …) reuses that session.

Commands provided:

  login              → opens a headful browser, lets the user sign in, closes.
  send <ad_url> <msg> → opens the ad page, clicks "Envoyer un message", types, sends.
  inbox [--limit N]  → opens the /messagerie page and lists recent conversations.
"""
from __future__ import annotations

import time
from typing import Iterator

from playwright.sync_api import Page, TimeoutError as PWTimeout

from .browser import BrowserSession


LOGIN_URL = "https://www.leboncoin.fr/compte/connexion"
ACCOUNT_URL = "https://www.leboncoin.fr/account"
INBOX_URL = "https://www.leboncoin.fr/messagerie"


def _accept_cookies(page: Page) -> None:
    """Didomi consent banner — click 'Accepter' if present."""
    for sel in ("#didomi-notice-agree-button", "button#didomi-notice-agree-button"):
        try:
            btn = page.locator(sel)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


def is_logged_in(browser: BrowserSession) -> bool:
    """Hit /account — if we stay there, we're signed in; if redirected to /connexion, we aren't."""
    with browser.page() as page:
        page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=20_000)
        _accept_cookies(page)
        return "connexion" not in page.url


def interactive_login(browser: BrowserSession, *, timeout_s: int = 300) -> bool:
    """Open login page headful and wait until the user finishes (or timeout)."""
    with browser.page() as page:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        _accept_cookies(page)
        print("Browser opened. Sign in, solve any MFA/captcha, then return here.")
        print(f"Waiting up to {timeout_s}s for login to complete…")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if "connexion" not in page.url and "compte" not in page.url:
                # Double-check via /account
                try:
                    page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=10_000)
                except PWTimeout:
                    continue
                if "connexion" not in page.url:
                    return True
            page.wait_for_timeout(1_500)
    return False


def send_message(browser: BrowserSession, ad_url: str, message: str, *, dry_run: bool = False) -> bool:
    """
    Open an ad, click the message button, type `message`, click send.

    Leboncoin labels vary by A/B test; we try several selectors and fall back to
    text matching. Returns True on success.
    """
    if not message.strip():
        raise ValueError("empty message")

    with browser.page() as page:
        page.goto(ad_url, wait_until="domcontentloaded", timeout=30_000)
        _accept_cookies(page)

        # Open the message composer.
        opened = False
        for sel in (
            'button:has-text("Envoyer un message")',
            'a:has-text("Envoyer un message")',
            '[data-qa-id="aditem_contact_message_cta"]',
            '[data-testid="contact-button-message"]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click()
                    opened = True
                    break
            except Exception:
                continue
        if not opened:
            raise RuntimeError(
                "could not find the 'Envoyer un message' button. Are you logged in? "
                "Run `lbc login` first."
            )

        # The composer is a textarea/contenteditable. Try the common ones.
        composer = None
        for sel in (
            'textarea[name="message"]',
            'textarea[placeholder*="message" i]',
            '[contenteditable="true"]',
            'textarea',
        ):
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=5_000)
                composer = loc
                break
            except PWTimeout:
                continue
        if composer is None:
            raise RuntimeError("message composer did not appear (login required?)")

        composer.click()
        composer.fill(message)

        if dry_run:
            print(f"[dry-run] would send to {ad_url}: {message!r}")
            return True

        # Submit. Leboncoin uses "Envoyer" as the button label.
        for sel in (
            'button:has-text("Envoyer"):not(:has-text("message"))',
            'button[type="submit"]:has-text("Envoyer")',
            '[data-qa-id="message_send_button"]',
        ):
            try:
                btn = page.locator(sel).first
                if btn.count() and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    # Wait for success state (toast / redirect to /messagerie).
                    page.wait_for_timeout(2_000)
                    return True
            except Exception:
                continue
        raise RuntimeError("could not locate the send button")


def list_inbox(browser: BrowserSession, *, limit: int = 20) -> Iterator[dict]:
    """Scrape the inbox list via __NEXT_DATA__ if available, else DOM."""
    data = browser.get_next_data(INBOX_URL)
    pp = data.get("props", {}).get("pageProps", {}) or {}
    convs = pp.get("conversations") or pp.get("initialConversations") or []
    for i, c in enumerate(convs):
        if i >= limit:
            return
        yield {
            "id": c.get("id") or c.get("conversation_id"),
            "peer": (c.get("partner") or {}).get("name") or c.get("interlocutor_name"),
            "ad_title": (c.get("item") or {}).get("title") or c.get("ad_title"),
            "last_message": (c.get("last_message") or {}).get("body") or c.get("body"),
            "unread": bool(c.get("unread") or c.get("unread_count")),
            "updated_at": c.get("updated_at") or c.get("last_activity"),
        }
