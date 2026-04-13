"""
Search helpers — build Leboncoin /recherche URLs, parse __NEXT_DATA__ results,
and paginate.

Leboncoin's /recherche page is a Next.js SSR page. All results are embedded in
<script id="__NEXT_DATA__"> as a JSON blob whose shape we learned by inspecting
the live page (see README — "Live schema notes"):

    props.pageProps.searchData = {
        total, total_all, max_pages, ads: [ <Ad shape> ],
    }
    props.pageProps.search = {
        filters: {keywords: {text}, location: {area: {lat, lng, radius}}, ...},
        sort_by, sort_order, offset, limit, limit_alu,
    }

We therefore *always* fetch HTML (via Playwright, so Datadome is happy) and
parse that one JSON. No reverse-engineered API calls needed.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Iterator

from .browser import BrowserSession
from .models import Ad, SearchResult


# Category id → slug. Leboncoin uses numeric ids in URLs under /c/<slug>/ but
# /recherche accepts `category=<id>`.
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


def build_url(
    text: str,
    *,
    page: int = 1,
    category: str | int | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int | None = None,
    locations: str | None = None,       # e.g. "r_12" (region) or "d_75" (dept)
    sort: str = "time",                 # "time" | "relevance" | "price"
    order: str = "desc",
    price_min: int | None = None,
    price_max: int | None = None,
    owner_type: str | None = None,      # "private" | "pro" | "all"
) -> str:
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


def parse_search_payload(next_data: dict[str, Any]) -> SearchResult:
    pp = next_data.get("props", {}).get("pageProps", {}) or {}
    sd = pp.get("searchData") or {}
    search = pp.get("search") or {}
    filters = (search.get("filters") or {}).get("keywords") or {}
    ads_raw = sd.get("ads") or []
    offset = int(search.get("offset") or 0)
    limit = int(search.get("limit") or 35) or 35
    page = (offset // limit) + 1
    return SearchResult(
        query=filters.get("text") or "",
        total=int(sd.get("total") or 0),
        page=page,
        max_pages=int(sd.get("max_pages") or 1),
        ads=[Ad.from_raw(a) for a in ads_raw],
        raw_payload=None,  # drop by default — users can re-fetch if they want raw
    )


def search_once(browser: BrowserSession, **kwargs: Any) -> SearchResult:
    url = build_url(**kwargs)
    data = browser.get_next_data(url)
    return parse_search_payload(data)


def search_paginated(
    browser: BrowserSession,
    *,
    max_results: int = 100,
    **kwargs: Any,
) -> Iterator[Ad]:
    """Yield ads across pages until max_results or max_pages is reached."""
    yielded = 0
    page = kwargs.pop("page", 1)
    while yielded < max_results:
        result = search_once(browser, page=page, **kwargs)
        if not result.ads:
            break
        for ad in result.ads:
            yield ad
            yielded += 1
            if yielded >= max_results:
                return
        if page >= result.max_pages:
            return
        page += 1
