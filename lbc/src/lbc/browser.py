"""
Browser layer. Persistent Chromium profile so the Datadome cookie + login
session survive across invocations.

### Why not api.leboncoin.fr
Empirically (April 2026) Datadome 403s any direct XHR to
`https://api.leboncoin.fr/finder/search` even when the browser context has a
valid Datadome cookie — that public `api_key` endpoint is now mobile-only.

### Why not `self.__next_f` at runtime
Leboncoin's website is Next.js App Router. The server streams RSC chunks into
`self.__next_f`. Once React hydrates, the runtime drains that array, so when
we probe it a beat later it is empty. We need the *raw* server HTML before
hydration touches it.

### What actually works
Two complementary strategies, tried in order:

1. **Raw HTTP via the browser context** (`context.request.get(url)`).
   Uses the same cookie jar as the browser — Datadome sees our valid cookie —
   and the response is the server-rendered HTML with every RSC chunk still
   sitting in `<script>…self.__next_f.push([1,"…"])…</script>` tags.
   We parse those chunks out, concatenate, and bracket-match the target JSON.
2. **Page navigation + DOM script-tag sweep** (fallback). Open the URL in a
   real tab, read every inline `<script>`'s textContent (those tags survive
   hydration), reconstruct the stream the same way. Slower but works if #1
   is challenged.

A final DOM-scrape fallback yields minimal cards from the rendered ads list.

Messaging still uses UI automation against the same persistent profile.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

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


# Matches `self.__next_f.push([<tag>,"<json-escaped string>"])` — the string
# value may contain escaped quotes / backslashes.
_NEXT_F_PUSH = re.compile(
    r'self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*("(?:[^"\\]|\\.)*")\s*\]\s*\)',
    re.DOTALL,
)


def _reconstruct_stream(html_or_scripts: str) -> str:
    """Concatenate every `self.__next_f.push(...)` payload found."""
    parts: list[str] = []
    for m in _NEXT_F_PUSH.finditer(html_or_scripts):
        try:
            parts.append(json.loads(m.group(1)))
        except Exception:
            pass
    return "".join(parts)


def _bracket_match(text: str, open_idx: int) -> Optional[str]:
    """String-aware `{...}` matcher. Returns the substring or None."""
    depth = 0
    in_str = False
    esc = False
    for i in range(open_idx, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
    return None


def find_object_by_key(stream: str, needle: str) -> Optional[dict]:
    """Find the first `"<needle>":{...}` and return the parsed object."""
    marker = f'"{needle}":'
    frm = 0
    while True:
        idx = stream.find(marker, frm)
        if idx == -1:
            return None
        j = idx + len(marker)
        # skip whitespace
        while j < len(stream) and stream[j] in " \n\t":
            j += 1
        if j < len(stream) and stream[j] == "{":
            blob = _bracket_match(stream, j)
            if blob:
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    pass
        frm = idx + len(marker)


def find_objects_by_list_id(stream: str) -> list[dict]:
    """Fallback: find every object containing `"list_id":<digits>`."""
    out: list[dict] = []
    for m in re.finditer(r'"list_id":\s*\d+', stream):
        # walk back to enclosing '{' (depth-aware)
        i = m.start()
        depth = 0
        while i > 0:
            i -= 1
            c = stream[i]
            if c == "}":
                depth += 1
            elif c == "{":
                if depth == 0:
                    break
                depth -= 1
        blob = _bracket_match(stream, i)
        if blob:
            try:
                out.append(json.loads(blob))
            except json.JSONDecodeError:
                pass
    return out


class BrowserSession:
    """Persistent Chromium session tailored for Leboncoin."""

    def __init__(self, *, headless: bool = True, slow_mo: int = 0,
                 debug_dir: Optional[Path] = None) -> None:
        self.headless = headless
        self.slow_mo = slow_mo
        self.debug_dir = debug_dir
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
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

    # -- core extraction ------------------------------------------------------

    def _debug_dump(self, name: str, text: str) -> None:
        if not self.debug_dir:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        (self.debug_dir / name).write_text(text)

    def _fetch_raw_html(self, url: str) -> Optional[str]:
        """Raw HTTP fetch through the browser context. Returns HTML or None."""
        assert self._ctx
        try:
            # Hint to Leboncoin that this is a top-level navigation.
            resp = self._ctx.request.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                    "Referer": "https://www.leboncoin.fr/",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-Dest": "document",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=25_000,
            )
        except Exception:
            return None
        if not resp.ok:
            return None
        html = resp.text()
        if "<title>" in html and ("datadome" in html.lower() or "captcha-delivery" in html.lower()):
            return None
        return html

    def _fetch_page_scripts(self, url: str, *, wait_selector: str | None,
                            wait_ms: int) -> tuple[Optional[str], str]:
        """Navigate to url in a real tab and return (script_text, title)."""
        with self.page() as page:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=wait_ms)
            except PWTimeout:
                return None, ""
            # Accept cookie banner (best-effort).
            try:
                btn = page.locator("#didomi-notice-agree-button").first
                if btn.count() and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(200)
            except Exception:
                pass
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=10_000)
                except PWTimeout:
                    pass
            # Collect every inline <script> textContent — these survive hydration.
            scripts = page.evaluate(
                "() => Array.from(document.querySelectorAll('script:not([src])'))"
                ".map(s => s.textContent || '').join('\\n')"
            )
            return scripts, page.title() or ""

    def extract_payload(
        self,
        url: str,
        *,
        needle: str | None = None,
        list_id_fallback: bool = False,
        wait_ms: int = 30_000,
        wait_selector: str | None = None,
    ) -> dict[str, Any]:
        """
        Return the JSON object keyed `<needle>` (or `{"ads": [...]}` via
        list_id fallback). Tries raw HTTP first, then live page scripts.
        """
        diagnostics: list[str] = []

        # ---- Strategy 1: raw HTTP through the cookie-bearing context ----
        html = self._fetch_raw_html(url)
        if html:
            self._debug_dump("page.html", html)
            stream = _reconstruct_stream(html)
            diagnostics.append(f"raw-http stream={len(stream)}")
            if needle:
                obj = find_object_by_key(stream, needle)
                if obj is not None:
                    return obj
            if list_id_fallback:
                ads = find_objects_by_list_id(stream)
                if ads:
                    return {"ads": ads, "_source": "raw-http-list_id"}

        # ---- Strategy 2: live page + script-tag sweep ----
        scripts, title = self._fetch_page_scripts(
            url, wait_selector=wait_selector, wait_ms=wait_ms
        )
        if scripts:
            self._debug_dump("scripts.txt", scripts)
            stream = _reconstruct_stream(scripts)
            diagnostics.append(f"dom-scripts stream={len(stream)}")
            if not stream:
                # Some pages drop the push wrapper — try the scripts verbatim.
                stream = scripts
                diagnostics.append(f"dom-scripts-verbatim stream={len(stream)}")
            if needle:
                obj = find_object_by_key(stream, needle)
                if obj is not None:
                    return obj
            if list_id_fallback:
                ads = find_objects_by_list_id(stream)
                if ads:
                    return {"ads": ads, "_source": "dom-scripts-list_id"}
            if "captcha" in title.lower() or "protection" in title.lower():
                raise RuntimeError(
                    f"Datadome challenge on {url!r} (title={title!r}). "
                    "Run `lbc login` headful to solve it."
                )

        raise RuntimeError(
            f"couldn't extract {needle!r} from {url!r}. Diagnostics: "
            + "; ".join(diagnostics or ["no response"])
            + ". Re-run with `--debug DIR` to dump the raw HTML for inspection."
        )
