"""
Browser layer. Uses Playwright with a *persistent* Chromium profile so:
  - Datadome cookie is solved once, reused afterwards
  - Login session survives across CLI invocations
  - Same fingerprint each run → fewer challenges

Leboncoin renders search / ad pages server-side and embeds the full JSON
payload in <script id="__NEXT_DATA__">. We fetch the HTML via a real browser
(so Datadome is happy), then parse the JSON. No XHR/API reverse-engineering
needed — which is why this is far more robust than hitting api.leboncoin.fr
directly.

Design notes
------------
* `BrowserSession` is a context manager that owns a persistent context.
* `.get_next_data(url)` navigates and returns the parsed Next.js payload.
* The profile dir lives under platformdirs user data so it persists across
  shell sessions.
* Headful by default for `login` (user needs to type); headless otherwise.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from platformdirs import user_data_dir
from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeout,
    sync_playwright,
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1440, "height": 900}
LOCALE = "fr-FR"
TIMEZONE = "Europe/Paris"


def profile_dir() -> Path:
    p = Path(user_data_dir("lbc", "lbc")) / "chromium-profile"
    p.mkdir(parents=True, exist_ok=True)
    return p


class BrowserSession:
    """Persistent Chromium session tailored for Leboncoin."""

    def __init__(self, *, headless: bool = True, slow_mo: int = 0) -> None:
        self.headless = headless
        self.slow_mo = slow_mo
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        # Persistent context = real profile on disk. Datadome cookie survives.
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir()),
            headless=self.headless,
            slow_mo=self.slow_mo,
            viewport=VIEWPORT,
            user_agent=UA,
            locale=LOCALE,
            timezone_id=TIMEZONE,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        # Hide the webdriver flag — low-cost stealth.
        self._ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()

    @property
    def context(self) -> BrowserContext:
        assert self._ctx, "BrowserSession not entered"
        return self._ctx

    @contextmanager
    def page(self) -> Iterator[Page]:
        assert self._ctx, "BrowserSession not entered"
        page = self._ctx.new_page()
        try:
            yield page
        finally:
            page.close()

    # -- high-level helpers ----------------------------------------------------

    def get_next_data(self, url: str, *, wait_ms: int = 20_000) -> dict[str, Any]:
        """
        Navigate to `url` and return the parsed __NEXT_DATA__ JSON.
        Raises RuntimeError if the page is a Datadome challenge or no data found.
        """
        with self.page() as page:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=wait_ms)
            except PWTimeout as e:
                raise RuntimeError(f"navigation timed out: {url}") from e

            # If Datadome served a challenge, the title is typically
            # "leboncoin - Protection" or similar and __NEXT_DATA__ is absent.
            try:
                page.wait_for_selector("script#__NEXT_DATA__", timeout=8_000)
            except PWTimeout:
                title = page.title()
                raise RuntimeError(
                    f"no __NEXT_DATA__ on {url} (title={title!r}) — "
                    "likely a Datadome challenge. Run `lbc login` once "
                    "(headful) to solve it interactively."
                )

            raw = page.locator("script#__NEXT_DATA__").inner_text()
            return json.loads(raw)
