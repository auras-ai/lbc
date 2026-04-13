"""Dataclasses for clean, normalized Leboncoin records."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ── date helpers ──────────────────────────────────────────────────────────────

def parse_lbc_date(s: str | None) -> Optional[datetime]:
    """Leboncoin emits naive datetimes in Europe/Paris, e.g. '2026-02-07 08:34:27'."""
    if not s:
        return None
    try:
        # Already-ISO forms work too.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def relative(dt: datetime | None, now: datetime | None = None) -> str:
    if not dt:
        return "?"
    now = now or datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = (now - dt).total_seconds()
    if delta < 0:
        return "dans le futur"
    for unit, secs in (("an", 31536000), ("mois", 2592000), ("sem", 604800),
                       ("j", 86400), ("h", 3600), ("min", 60)):
        n = int(delta // secs)
        if n >= 1:
            return f"il y a {n} {unit}"
    return "à l’instant"


# ── models ────────────────────────────────────────────────────────────────────

@dataclass
class Location:
    city: Optional[str] = None
    zipcode: Optional[str] = None
    department: Optional[str] = None
    region: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> "Location":
        raw = raw or {}
        return cls(
            city=raw.get("city"),
            zipcode=raw.get("zipcode"),
            department=raw.get("department_name"),
            region=raw.get("region_name"),
            lat=raw.get("lat"),
            lng=raw.get("lng"),
        )

    def __str__(self) -> str:
        parts = [p for p in (self.city, self.zipcode, self.department) if p]
        return ", ".join(parts) or "?"


@dataclass
class Owner:
    name: Optional[str] = None
    user_id: Optional[str] = None
    store_id: Optional[str] = None
    type: Optional[str] = None  # "private" | "pro"

    @property
    def is_pro(self) -> bool:
        return self.type == "pro"

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> "Owner":
        raw = raw or {}
        return cls(
            name=raw.get("name"),
            user_id=raw.get("user_id"),
            store_id=raw.get("store_id"),
            type=raw.get("type"),
        )


@dataclass
class Ad:
    id: str
    title: str
    url: str
    price: Optional[int]
    price_cents: Optional[int]
    buyer_fee_cents: Optional[int]
    category_id: Optional[str]
    category_name: Optional[str]
    published_at: Optional[datetime]
    indexed_at: Optional[datetime]
    body: str
    location: Location
    owner: Owner
    images: list[str] = field(default_factory=list)
    thumb: Optional[str] = None
    attributes: dict[str, str] = field(default_factory=dict)
    has_phone: bool = False
    status: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Ad":
        price_list = raw.get("price") or []
        price = int(price_list[0]) if price_list else None
        bf = raw.get("buyer_fee") or {}
        attrs = {
            a["key"]: a.get("value_label") or a.get("value")
            for a in (raw.get("attributes") or [])
            if isinstance(a, dict) and a.get("key")
        }
        imgs = raw.get("images") or {}
        return cls(
            id=str(raw.get("list_id", "")),
            title=raw.get("subject", "") or "",
            url=raw.get("url") or f"https://www.leboncoin.fr/ad/item/{raw.get('list_id')}",
            price=price,
            price_cents=raw.get("price_cents"),
            buyer_fee_cents=bf.get("amount"),
            category_id=str(raw.get("category_id")) if raw.get("category_id") is not None else None,
            category_name=raw.get("category_name"),
            published_at=parse_lbc_date(raw.get("first_publication_date")),
            indexed_at=parse_lbc_date(raw.get("index_date")),
            body=raw.get("body") or "",
            location=Location.from_raw(raw.get("location")),
            owner=Owner.from_raw(raw.get("owner")),
            images=list(imgs.get("urls_large") or []),
            thumb=imgs.get("thumb_url") or imgs.get("small_url"),
            attributes=attrs,
            has_phone=bool(raw.get("has_phone")),
            status=raw.get("status"),
        )

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        d["indexed_at"] = self.indexed_at.isoformat() if self.indexed_at else None
        d["published_relative"] = relative(self.published_at)
        d["is_pro"] = self.owner.is_pro
        return d


@dataclass
class SearchResult:
    query: str
    total: int
    page: int
    max_pages: int
    ads: list[Ad]
    raw_payload: Optional[dict[str, Any]] = None
