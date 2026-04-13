"""Pydantic response schemas — mirrors the dataclass models for JSON serialization."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LocationOut(BaseModel):
    city: Optional[str] = None
    zipcode: Optional[str] = None
    department: Optional[str] = None
    region: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class OwnerOut(BaseModel):
    name: Optional[str] = None
    user_id: Optional[str] = None
    store_id: Optional[str] = None
    type: Optional[str] = None
    is_pro: bool = False


class AdOut(BaseModel):
    id: str
    title: str
    url: str
    price: Optional[int] = None
    price_cents: Optional[int] = None
    buyer_fee_cents: Optional[int] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    published_at: Optional[str] = None
    indexed_at: Optional[str] = None
    published_relative: Optional[str] = None
    body: str = ""
    location: LocationOut = LocationOut()
    owner: OwnerOut = OwnerOut()
    images: list[str] = []
    thumb: Optional[str] = None
    attributes: dict[str, str] = {}
    has_phone: bool = False
    status: Optional[str] = None


class SearchOut(BaseModel):
    query: str
    total: int
    page: int
    max_pages: int
    ads: list[AdOut]


class InboxConversation(BaseModel):
    id: Optional[str] = None
    peer: Optional[str] = None
    ad_title: Optional[str] = None
    last_message: Optional[str] = None
    unread: bool = False
    updated_at: Optional[str] = None


class MessageRequest(BaseModel):
    ad_url: str
    message: str
    dry_run: bool = False


class StatusOut(BaseModel):
    status: str
    logged_in: bool
