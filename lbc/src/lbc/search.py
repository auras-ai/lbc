"""
Search helpers — build the filter payload for /finder/search, call it via
BrowserSession.api_call (so Datadome cookie is attached), and paginate.

The /finder/search response is:
    {
      "ads": [ <same shape as searchData.ads[i]> ],
      "total": 303,
      "total_all": 303,
      "max_pages": 9,
      "pivot": "...",
      ...
    }

which is exactly the payload `Ad.from_raw` already handles (we reverse-engineered
the shape in the Chrome inspection step; see README § "Live schema notes").
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Iterator

from .browser import BrowserSession
from .models import Ad, SearchResult


CATEGORIES: dict[str, int] = {
    "voitures": 2, "motos": 3,
    "informatique": 15, "ordinateurs": 15, "accessoires_informatique": 17,
    "consoles": 11, "jeux_video": 43, "telephonie": 16, "image_son": 14,
    "electromenager": 20, "meubles": 19, "decoration": 21,
    "vetements": 22, "chaussures": 53,
    "sports_hobbies": 29, "musique": 26, "velos": 55,
    "immobilier": 9, "locations": 10, "services": 76,
}

BASE = "https://www.leboncoin.fr/recherche"
DEFAULT_LIMIT = 35
AD_CARD_SELECTOR = 'a[data-test-id="ad"], a[href*="/ad/"]'


def build_url(
    text: str,
    *,
    page: int = 1,
    category: str | int | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int | None = None,
    locations: str | None = None,
    sort: str = "time",
    order: str = "desc",
    price_min: int | None = None,
    price_max: int | None = None,
    owner_type: str | None = None,
) -> str:
    """Reproduces the canonical /recherche URL (used for --show-url)."""
    q: dict[str, Any] = {"text": text, "sort": sort, "order": order, "page": page}
    if category is not None:
        cat_id = CATEGORIES.get(str(category).lower()) if not isinstance(category, int) else category
        if cat_id is None:
            raise ValueError(f"unknown category: {category}")
        q["category"] = cat_id
    if lat is not None and lng is not None:
        q["lat"] = lat
        q["lng"] = lng
        if radius_m is not None:
            q["radius"] = radius_m
    if locations:
        q["locations"] = locations
    if price_min is not None or price_max is not None:
        lo = price_min if price_min is not None else ""
        hi = price_max if price_max is not None else ""
        q["price"] = f"{lo}-{hi}"
    if owner_type and owner_type != "all":
        q["owner_type"] = "private" if owner_type == "private" else "pro"
    return f"{BASE}?{urllib.parse.urlencode(q)}"


def build_filters(
    text: str,
    *,
    category: str | int | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    owner_type: str | None = None,
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "keywords": {"text": text},
        "enums": {"ad_type": ["offer"]},
        "ranges": {},
    }
    if category is not None:
        cat_id = CATEGORIES.get(str(category).lower()) if not isinstance(category, int) else category
        if cat_id is None:
            raise ValueError(f"unknown category: {category}")
        filters["category"] = {"id": str(cat_id)}
    if lat is not None and lng is not None:
        area: dict[str, Any] = {"lat": lat, "lng": lng}
        if radius_m is not None:
            area["radius"] = radius_m
        filters["location"] = {"area": area}
    if price_min is not None or price_max is not None:
        r: dict[str, int] = {}
        if price_min is not None:
            r["min"] = price_min
        if price_max is not None:
            r["max"] = price_max
        filters["ranges"]["price"] = r
    if owner_type and owner_type != "all":
        filters["owner"] = {"type": "private" if owner_type == "private" else "pro"}
    if not filters["ranges"]:
        del filters["ranges"]
    return filters


def parse_search_data(data: dict[str, Any], *, page: int, query: str) -> SearchResult:
    ads_raw = data.get("ads") or []
    total = int(data.get("total") or data.get("total_all") or 0)
    max_pages = int(data.get("max_pages") or max(1, (total + DEFAULT_LIMIT - 1) // DEFAULT_LIMIT))
    return SearchResult(
        query=query,
        total=total,
        page=page,
        max_pages=max_pages,
        ads=[Ad.from_raw(a) for a in ads_raw],
    )


def search_once(
    browser: BrowserSession,
    *,
    page: int = 1,
    sort: str = "time",
    order: str = "desc",
    **kwargs: Any,
) -> SearchResult:
    # Build the SAME canonical URL as the web UI — Leboncoin SSR renders
    # exactly this view, and we pull `searchData` out of the RSC stream.
    url = build_url(page=page, sort=sort, order=order, **kwargs)
    data = browser.extract_payload(
        url,
        needle="searchData",
        list_id_fallback=True,
        wait_selector=AD_CARD_SELECTOR,
    )
    return parse_search_data(data, page=page, query=kwargs.get("text", "") or "")


def search_paginated(
    browser: BrowserSession,
    *,
    max_results: int = 100,
    page: int = 1,
    sort: str = "time",
    order: str = "desc",
    **kwargs: Any,
) -> Iterator[Ad]:
    """Yield ads across pages until max_results or max_pages is reached."""
    yielded = 0
    while yielded < max_results:
        result = search_once(browser, page=page, sort=sort, order=order, **kwargs)
        if not result.ads:
            return
        for ad in result.ads:
            yield ad
            yielded += 1
            if yielded >= max_results:
                return
        if page >= result.max_pages:
            return
        page += 1
