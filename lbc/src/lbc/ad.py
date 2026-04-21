"""Single-ad detail via RSC-stream extraction from the ad page HTML."""
from __future__ import annotations

from typing import Any

from .browser import BrowserSession
from .models import Ad


def fetch_ad(browser: BrowserSession, ad_id: str | int, *, category_slug: str = "item") -> Ad:
    """
    /ad/<slug>/<id> is server-rendered. Ad object lives in `self.__next_f`
    under the key `"ad":{...}`. `"item"` as slug works (Leboncoin resolves it).
    """
    url = f"https://www.leboncoin.fr/ad/{category_slug}/{ad_id}"
    data: dict[str, Any] = browser.extract_payload(
        url,
        needle="ad",
        list_id_fallback=True,
        wait_selector='[data-qa-id="adview_title"], h1',
    )
    # `extract_payload` may return either the `ad` object itself (needle match)
    # or `{"ads": [<objects containing list_id>]}` from the fallback path.
    if "ads" in data and isinstance(data["ads"], list) and data["ads"]:
        raw = data["ads"][0]
    elif "list_id" in data:
        raw = data
    else:
        raise RuntimeError(f"unexpected ad payload shape for {ad_id}: keys={list(data)[:6]}")
    return Ad.from_raw(raw)
