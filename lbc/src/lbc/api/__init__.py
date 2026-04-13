"""
lbc API — FastAPI application exposing the scraper as a REST service.

Mirrors the service-layer pattern from the SeaORM actix_example:
  - service/query.py   → read operations (search, ad detail, inbox, auth)
  - service/mutation.py → write operations (send message)
  - schemas.py          → Pydantic response/request models
  - __init__.py          → FastAPI routes + app factory
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Query

from ..browser import BrowserSession
from .schemas import AdOut, InboxConversation, MessageRequest, SearchOut, StatusOut
from .service import MutationService, QueryService

# Playwright sync API cannot run inside asyncio's event loop. We run it in a
# dedicated daemon thread that owns the browser session. All route handlers
# submit work to that thread via _run_in_browser_thread().

_browser: BrowserSession | None = None
_browser_ready = threading.Event()


def _browser_thread(headless: bool) -> None:
    global _browser
    _browser = BrowserSession(headless=headless)
    _browser.__enter__()
    _browser_ready.set()
    # Block forever — lifespan teardown calls __exit__ from the main thread.
    threading.Event().wait()


def _run_in_browser_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a sync function that needs the browser in the browser thread."""
    import asyncio
    # We cannot easily dispatch to the browser thread since Playwright objects
    # are bound to the thread that created them. Instead, the simplest correct
    # approach is to run the blocking call in a *new* thread via asyncio's
    # executor — but that also fails because BrowserSession uses thread-local
    # Playwright. The pragmatic fix: since all our service functions are short-
    # lived sync calls, we run them in the default executor (thread pool) and
    # create a fresh BrowserSession per call.
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, partial(fn, *args, **kwargs))


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="lbc API",
    description="REST API for Leboncoin search, ad details, and messaging.",
    version="0.2.0",
    lifespan=lifespan,
)

_headless = os.getenv("LBC_HEADLESS", "true").lower() in ("true", "1", "yes")


def _with_browser(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Create a fresh BrowserSession, run fn, close. Thread-safe."""
    with BrowserSession(headless=_headless) as browser:
        return fn(browser, *args, **kwargs)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Search ───────────────────────────────────────────────────────────────────

@app.get("/api/search", response_model=SearchOut)
async def search(
    q: str = Query(..., description="Search text"),
    page: int = Query(1, ge=1),
    limit: int = Query(35, ge=1, le=200),
    category: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    radius: Optional[int] = Query(None, description="Radius in meters"),
    sort: str = Query("time", pattern="^(time|relevance|price)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    price_min: Optional[int] = Query(None, ge=0),
    price_max: Optional[int] = Query(None, ge=0),
    owner_type: Optional[str] = Query(None, pattern="^(private|pro|all)$"),
):
    import asyncio
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None,
            partial(
                _with_browser,
                QueryService.search,
                text=q, page=page, limit=limit, category=category,
                lat=lat, lng=lng, radius_m=radius,
                sort=sort, order=order,
                price_min=price_min, price_max=price_max,
                owner_type=owner_type,
            ),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Ad detail ────────────────────────────────────────────────────────────────

@app.get("/api/ads/{ad_id}", response_model=AdOut)
async def get_ad(ad_id: str):
    import asyncio
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(_with_browser, QueryService.get_ad, ad_id),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Auth status ──────────────────────────────────────────────────────────────

@app.get("/api/whoami", response_model=StatusOut)
async def whoami():
    import asyncio
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(_with_browser, QueryService.check_auth),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Inbox ────────────────────────────────────────────────────────────────────

def _inbox_with_auth(browser: BrowserSession, limit: int) -> list[InboxConversation]:
    from ..messaging import is_logged_in as _is_logged_in
    if not _is_logged_in(browser):
        raise HTTPException(status_code=401, detail="Not logged in. Use lbc login first.")
    return QueryService.get_inbox(browser, limit=limit)


@app.get("/api/inbox", response_model=list[InboxConversation])
async def inbox(limit: int = Query(20, ge=1, le=100)):
    import asyncio
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(_with_browser, _inbox_with_auth, limit=limit),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Send message ─────────────────────────────────────────────────────────────

def _send_with_auth(browser: BrowserSession, ad_url: str, message: str, dry_run: bool) -> dict:
    from ..messaging import is_logged_in as _is_logged_in
    if not _is_logged_in(browser):
        raise HTTPException(status_code=401, detail="Not logged in. Use lbc login first.")
    ok = MutationService.send_message(browser, ad_url, message, dry_run=dry_run)
    return {"sent": ok, "dry_run": dry_run}


@app.post("/api/messages")
async def send_message(req: MessageRequest):
    import asyncio
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None,
            partial(_with_browser, _send_with_auth, req.ad_url, req.message, req.dry_run),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
