"""Read-only operations — search, ad detail, inbox, auth status."""
from __future__ import annotations

from typing import Optional

from ...browser import BrowserSession
from ...search import search_once, search_paginated
from ...ad import fetch_ad
from ...messaging import is_logged_in, list_inbox
from ...models import Ad
from ..schemas import AdOut, SearchOut, InboxConversation, StatusOut


def _ad_to_out(ad: Ad) -> AdOut:
    d = ad.to_json()
    d["owner"]["is_pro"] = ad.owner.is_pro
    return AdOut(**d)


class QueryService:

    @staticmethod
    def search(
        browser: BrowserSession,
        text: str,
        *,
        page: int = 1,
        limit: int = 35,
        category: str | int | None = None,
        lat: float | None = None,
        lng: float | None = None,
        radius_m: int | None = None,
        sort: str = "time",
        order: str = "desc",
        price_min: int | None = None,
        price_max: int | None = None,
        owner_type: str | None = None,
    ) -> SearchOut:
        ads = list(search_paginated(
            browser,
            max_results=limit,
            text=text,
            page=page,
            category=category,
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            sort=sort,
            order=order,
            price_min=price_min,
            price_max=price_max,
            owner_type=owner_type,
        ))
        result = search_once(
            browser,
            text=text,
            page=page,
            category=category,
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            sort=sort,
            order=order,
            price_min=price_min,
            price_max=price_max,
            owner_type=owner_type,
        )
        return SearchOut(
            query=text,
            total=result.total,
            page=result.page,
            max_pages=result.max_pages,
            ads=[_ad_to_out(a) for a in ads],
        )

    @staticmethod
    def get_ad(browser: BrowserSession, ad_id: str) -> AdOut:
        ad = fetch_ad(browser, ad_id)
        return _ad_to_out(ad)

    @staticmethod
    def check_auth(browser: BrowserSession) -> StatusOut:
        logged = is_logged_in(browser)
        return StatusOut(
            status="authenticated" if logged else "not_authenticated",
            logged_in=logged,
        )

    @staticmethod
    def get_inbox(browser: BrowserSession, *, limit: int = 20) -> list[InboxConversation]:
        convs = list(list_inbox(browser, limit=limit))
        return [InboxConversation(**c) for c in convs]
