"""Offline smoke test: parser + YAML/JSON rendering against a captured payload.

Exercises build_url, build_filters, parse_api_payload and Ad.to_json end-to-end
without launching a browser.
"""
from __future__ import annotations

import json

import yaml

from lbc.browser import (
    _reconstruct_stream,
    find_object_by_key,
    find_objects_by_list_id,
)
from lbc.models import Ad, relative
from lbc.search import build_filters, build_url, parse_search_data


# What /finder/search returns (same shape as the old searchData embedded in
# __NEXT_DATA__, captured live from Leboncoin).
API_RESPONSE = {
    "total": 303, "total_all": 303, "max_pages": 9,
    "ads": [
        {
            "list_id": 3140748683,
            "first_publication_date": "2026-02-07 08:34:27",
            "index_date": "2026-02-07 08:34:27",
            "category_id": "15", "category_name": "Ordinateurs",
            "subject": "Lot de 2 IMac Pro 27 pouces",
            "body": "Je vends un lot de 2 iMac Pro de 2017...",
            "ad_type": "offer",
            "url": "https://www.leboncoin.fr/ad/ordinateurs/3140748683",
            "price": [2300], "price_cents": 230000,
            "buyer_fee": {"amount": 99},
            "images": {
                "nb_images": 8,
                "thumb_url": "https://img.leboncoin.fr/t.jpg",
                "small_url": "https://img.leboncoin.fr/s.jpg",
                "urls_large": ["https://img.leboncoin.fr/a.jpg",
                               "https://img.leboncoin.fr/b.jpg"],
            },
            "attributes": [
                {"key": "rating_score", "value_label": "1"},
                {"key": "estimated_parcel_size", "value_label": "M"},
            ],
            "location": {
                "city": "Capbreton", "zipcode": "40130",
                "department_name": "Landes", "region_name": "Aquitaine",
                "lat": 43.64003, "lng": -1.43087,
            },
            "owner": {
                "name": "Barouillet",
                "user_id": "525ea49d-a0c8-481b-a435-870bb74f8ef5",
                "store_id": "6809463", "type": "private",
            },
            "has_phone": False, "status": "active",
        }
    ],
}


def simulate_rsc_html(search_data: dict) -> str:
    """Build an HTML page that mimics Leboncoin's streaming chunks."""
    # Each push payload is a JSON-encoded string; inside it, we embed a flight
    # row that itself contains `"searchData": <object>`.
    sd = json.dumps(search_data, ensure_ascii=False)
    flight_row = '7:{"props":{"pageProps":{"searchData":' + sd + '}}}\n'
    # Split into two pushes to exercise concat.
    half = len(flight_row) // 2
    part1 = json.dumps(flight_row[:half], ensure_ascii=False)
    part2 = json.dumps(flight_row[half:], ensure_ascii=False)
    return (
        "<!doctype html><html><body>"
        f"<script>self.__next_f.push([1,{part1}])</script>"
        f"<script>self.__next_f.push([1,{part2}])</script>"
        "</body></html>"
    )


def main() -> None:
    # Build a fake Leboncoin-like HTML with RSC chunks and exercise the
    # real extractor pipeline (HTML → _reconstruct_stream → find_object_by_key).
    html = simulate_rsc_html(API_RESPONSE)
    stream = _reconstruct_stream(html)
    assert stream, "_reconstruct_stream produced empty output"
    extracted = find_object_by_key(stream, "searchData")
    assert extracted is not None, "couldn't find searchData"
    assert extracted["total"] == 303
    assert extracted["ads"][0]["list_id"] == 3140748683
    # list_id fallback
    ads = find_objects_by_list_id(stream)
    assert any(a.get("list_id") == 3140748683 for a in ads), "list_id fallback failed"
    print("RSC extractor OK")

    # URL builder (for --show-url)
    url = build_url(
        text="imac", lat=43.33935135824864, lng=-0.6907025372342671,
        radius_m=100000, sort="time", order="desc", page=3,
    )
    assert "text=imac" in url and "radius=100000" in url and "page=3" in url

    # API filter builder
    filters = build_filters(
        text="rtx 4090", lat=48.8566, lng=2.3522, radius_m=20000,
        price_min=500, price_max=1500, owner_type="private",
    )
    assert filters["keywords"]["text"] == "rtx 4090"
    assert filters["location"]["area"] == {"lat": 48.8566, "lng": 2.3522, "radius": 20000}
    assert filters["ranges"]["price"] == {"min": 500, "max": 1500}
    assert filters["owner"]["type"] == "private"

    # searchData payload parsing (same shape whether from /finder/search or RSC)
    result = parse_search_data(API_RESPONSE, page=3, query="imac")
    assert result.total == 303
    assert result.max_pages == 9
    assert result.page == 3
    ad: Ad = result.ads[0]
    assert ad.id == "3140748683"
    assert ad.price == 2300
    assert ad.price_cents == 230000
    assert ad.buyer_fee_cents == 99
    assert ad.location.city == "Capbreton"
    assert ad.owner.is_pro is False
    assert ad.published_at and ad.published_at.isoformat().startswith("2026-02-07T08:34:27")
    assert ad.attributes["estimated_parcel_size"] == "M"

    print("--- JSON ---")
    print(json.dumps(ad.to_json(), indent=2, ensure_ascii=False, default=str))
    print("\n--- YAML ---")
    print(yaml.safe_dump(
        [ad.to_json()], sort_keys=False, allow_unicode=True, default_flow_style=False
    ))
    print("published_relative:", relative(ad.published_at))
    print("OK")


if __name__ == "__main__":
    main()
