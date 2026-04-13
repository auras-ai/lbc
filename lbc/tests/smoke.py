"""Offline smoke test: parser + CLI rendering against a captured payload."""
from __future__ import annotations

import json

from lbc.models import Ad, relative
from lbc.search import parse_search_payload, build_url

FIXTURE = {
    "props": {
        "pageProps": {
            "search": {
                "filters": {
                    "keywords": {"text": "imac"},
                    "location": {"area": {"lat": 43.339, "lng": -0.690, "radius": 100000}},
                    "enums": {"ad_type": ["offer"]},
                },
                "sort_by": "time", "sort_order": "desc",
                "offset": 70, "limit": 35, "limit_alu": 2,
            },
            "searchData": {
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
            },
        }
    }
}


def main() -> None:
    # URL builder
    url = build_url(
        text="imac", lat=43.33935135824864, lng=-0.6907025372342671,
        radius_m=100000, sort="time", order="desc", page=3,
    )
    assert "text=imac" in url
    assert "lat=43.33935135824864" in url
    assert "page=3" in url
    print("url:", url)

    # Search payload parsing
    result = parse_search_payload(FIXTURE)
    assert result.total == 303
    assert result.max_pages == 9
    assert result.page == 3, result.page   # offset 70 / limit 35 = page 3
    assert len(result.ads) == 1
    ad: Ad = result.ads[0]
    assert ad.id == "3140748683"
    assert ad.price == 2300
    assert ad.price_cents == 230000
    assert ad.buyer_fee_cents == 99
    assert ad.category_name == "Ordinateurs"
    assert ad.location.city == "Capbreton"
    assert ad.location.zipcode == "40130"
    assert ad.owner.name == "Barouillet"
    assert ad.owner.is_pro is False
    assert ad.published_at is not None
    assert ad.published_at.isoformat().startswith("2026-02-07T08:34:27")
    assert "estimated_parcel_size" in ad.attributes
    assert ad.attributes["estimated_parcel_size"] == "M"
    assert len(ad.images) == 2
    print("parsed ad:")
    print(json.dumps(ad.to_json(), indent=2, ensure_ascii=False, default=str))
    print("published_relative:", relative(ad.published_at))
    print("OK")


if __name__ == "__main__":
    main()
