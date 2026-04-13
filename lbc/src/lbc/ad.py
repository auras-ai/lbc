"""Single-ad detail fetcher — same SSR trick as search."""
from __future__ import annotations

from typing import Any

from .browser import BrowserSession
from .models import Ad


def fetch_ad(browser: BrowserSession, ad_id: str | int, *, category_slug: str = "item") -> Ad:
    """
    Ad URLs look like https://www.leboncoin.fr/ad/<category_slug>/<id>.
    Any slug works for navigation (server redirects to canonical) — "item" is safe.
    """
    url = f"https://www.leboncoin.fr/ad/{category_slug}/{ad_id}"
    data = browser.get_next_data(url)
    pp: dict[str, Any] = data.get("props", {}).get("pageProps", {}) or {}
    raw = pp.get("ad") or pp.get("initialAd")
    if not raw:
        raise RuntimeError(f"ad payload missing in __NEXT_DATA__ for {ad_id}")
    return Ad.from_raw(raw)
