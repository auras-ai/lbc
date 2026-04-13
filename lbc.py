#!/usr/bin/env python3
"""
lbc — Leboncoin CLI scraper
Combines DuckDuckGo + Startpage to get listings with prices and dates.
Falls back to direct Leboncoin API when on residential IP.

Usage:
    python3 lbc.py search "rtx 3090"
    python3 lbc.py search "iphone 15" --limit 20
    python3 lbc.py search "velo electrique" --category sports_hobbies
    python3 lbc.py search "rtx 3090" --json
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from html import unescape
from typing import Optional

CATEGORIES = {
    "voitures": 2, "motos": 3, "informatique": 15, "ordinateurs": 15,
    "accessoires_informatique": 17, "consoles": 11, "jeux_video": 43,
    "telephonie": 16, "image_son": 14, "electromenager": 20,
    "meubles": 19, "decoration": 21, "vetements": 22, "chaussures": 53,
    "sports_hobbies": 29, "musique": 26, "velos": 55,
    "immobilier": 9, "locations": 10, "services": 76,
}

LBC_API_KEY = "ba0c2dad52b3ec"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _clean(text: str) -> str:
    return re.sub(r'<[^>]+>', '', unescape(text)).replace('&nbsp;', ' ').replace('\xa0', ' ').strip()


def _extract_price(text: str) -> Optional[str]:
    m = re.search(r'(\d[\d\s,.]*)\s*€', text)
    if m:
        return m.group(1).replace(' ', '').replace('\xa0', '').strip()
    return None


# ── Startpage (Google proxy — gives dates) ──

def startpage_search(query: str, limit: int = 20) -> list[dict]:
    url = "https://www.startpage.com/sp/search"
    payload = urllib.parse.urlencode({"query": query, "cat": "web"}).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "text/html")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode()
    except Exception:
        return []

    results = []
    seen = set()

    for m in re.finditer(
        r'"clickUrl":"(https://www\.leboncoin\.fr/ad/([^/]+)/(\d+))",'
        r'"description":"((?:[^"\\]|\\.)*)","displayUrl":"(?:[^"\\]|\\.)*",'
        r'"extraArgs":"[^"]*","faviconData":"(?:[^"\\]|\\.)*",'
        r'"siteLinks":\[[^\]]*\],"siteTitleData":"(?:[^"\\]|\\.)*",'
        r'"sourceIndex":\d+,"thash":"[^"]*","title":"((?:[^"\\]|\\.)*)"',
        html
    ):
        ad_id = m.group(3)
        if ad_id in seen:
            continue
        seen.add(ad_id)

        raw_desc = m.group(4).replace('\\n', '\n').replace("\\'", "'")
        desc = _clean(raw_desc)
        title = _clean(m.group(5)).replace(' - Leboncoin', '').replace(' - leboncoin', '')

        date = None
        dm = re.match(r'(\d+\s+(?:day|hour|minute|week|month)s?\s+ago|\d+\s+\w{3,9}\s+\d{4})', desc)
        if dm:
            date = dm.group(1)
            desc = desc[len(date):].strip().lstrip('. ')

        results.append({
            "id": ad_id,
            "title": title,
            "price": _extract_price(desc + " " + title),
            "date": date,
            "category": m.group(2),
            "snippet": desc[:250],
            "url": m.group(1),
        })
        if len(results) >= limit:
            break

    return results


# ── DuckDuckGo (sometimes catches prices) ──

def ddg_search(query: str, limit: int = 25) -> list[dict]:
    q = f"site:leboncoin.fr/ad {query}"
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode()
    except Exception:
        return []

    raw = re.findall(
        r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL,
    )

    ads = []
    for raw_url, raw_title, raw_snippet in raw:
        um = re.search(r'uddg=([^&]+)', raw_url)
        if not um:
            continue
        actual_url = urllib.parse.unquote(um.group(1))
        am = re.search(r'/ad/([^/]+)/(\d+)', actual_url)
        if not am:
            continue

        title = _clean(raw_title)
        snippet = _clean(raw_snippet)

        ads.append({
            "id": am.group(2),
            "title": title.replace(' - leboncoin', '').replace(' - Accessoires informatique', '').strip(),
            "price": _extract_price(snippet + " " + title),
            "date": None,
            "category": am.group(1),
            "snippet": snippet[:250],
            "url": actual_url,
        })
        if len(ads) >= limit:
            break
    return ads


# ── Direct Leboncoin API (residential IP only) ──

def lbc_api_search(query: str, category_id: Optional[int] = None, limit: int = 35) -> list[dict]:
    url = "https://api.leboncoin.fr/finder/search"
    filters: dict = {"keywords": {"text": query}, "enums": {"ad_type": ["offer"]}}
    if category_id:
        filters["category"] = {"id": str(category_id)}

    payload = json.dumps({
        "limit": limit, "limit_alu": 3,
        "filters": filters, "sort_by": "time", "sort_order": "desc",
    }).encode()

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("api_key", LBC_API_KEY)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    req.add_header("Origin", "https://www.leboncoin.fr")
    req.add_header("Referer", "https://www.leboncoin.fr/")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if "ads" not in data:
                return []
            ads = []
            for ad in data["ads"]:
                price = None
                if ad.get("price"):
                    price = str(ad["price"][0]) if isinstance(ad["price"], list) else str(ad["price"])
                loc = ad.get("location", {})
                location = ", ".join(p for p in [loc.get("city"), loc.get("department_name")] if p) or None
                ads.append({
                    "id": str(ad.get("list_id", "")),
                    "title": ad.get("subject", ""),
                    "price": price,
                    "date": ad.get("first_publication_date", ""),
                    "category": ad.get("category_name", ""),
                    "location": location,
                    "snippet": (ad.get("body", "") or "")[:250],
                    "url": ad.get("url", f"https://www.leboncoin.fr/ad/{ad.get('category_name','item')}/{ad.get('list_id','')}"),
                    "images": [i.get("urls", {}).get("default", "") for i in (ad.get("images", {}).get("urls_large", []) or [])[:3]],
                    "pro": ad.get("owner", {}).get("type") == "pro",
                })
            return ads
    except Exception:
        return []


# ── Combined search: merge sources for best coverage ──

def combined_search(query: str, category: Optional[str] = None, limit: int = 20) -> tuple[list[dict], str]:
    cat_id = CATEGORIES.get((category or "").lower().replace(" ", "_"))
    cat_suffix = f" {category}" if category and not cat_id else ""

    # 1. Try direct API first (works on residential IP)
    ads = lbc_api_search(query, category_id=cat_id, limit=limit)
    if ads:
        return ads, "API Leboncoin"

    # 2. Startpage (Google results with dates)
    sp_ads = startpage_search(f'site:leboncoin.fr/ad "{query}"{cat_suffix}', limit=limit)

    # 3. DuckDuckGo (sometimes has prices)
    ddg_ads = ddg_search(f"{query}{cat_suffix} €", limit=limit)

    # Merge: Startpage as base, enrich with DDG prices
    merged: dict[str, dict] = {}
    for ad in sp_ads:
        merged[ad["id"]] = ad
    for ad in ddg_ads:
        if ad["id"] not in merged:
            merged[ad["id"]] = ad
        else:
            if ad.get("price") and not merged[ad["id"]].get("price"):
                merged[ad["id"]]["price"] = ad["price"]
            if ad.get("snippet") and len(ad["snippet"]) > len(merged[ad["id"]].get("snippet", "")):
                merged[ad["id"]]["snippet"] = ad["snippet"]

    result = list(merged.values())[:limit]
    sources = []
    if sp_ads:
        sources.append("Startpage")
    if ddg_ads:
        sources.append("DuckDuckGo")
    return result, " + ".join(sources) or "none"


def format_results(ads: list[dict], source: str):
    if not ads:
        print("Aucune annonce trouvee.")
        return

    print(f"\n\U0001f50d {len(ads)} annonces trouvees (via {source})\n")
    for i, ad in enumerate(ads, 1):
        price_str = f"{int(float(ad['price'])):,} \u20ac".replace(",", " ") if ad.get("price") else "Prix ?"
        date_str = ad.get("date") or "?"
        loc_str = f"  \U0001f4cd {ad['location']}" if ad.get("location") else ""

        title = ad["title"][:70]
        print(f"[{i}] {title}")
        print(f"    \U0001f4b0 {price_str}  \U0001f4c5 {date_str}{loc_str}")
        if ad.get("snippet"):
            snip = ad["snippet"][:120]
            if len(ad.get("snippet", "")) > 120:
                snip += "..."
            print(f"    {snip}")
        print(f"    \U0001f517 {ad['url']}")
        print()


def cmd_search(args):
    ads, source = combined_search(args.query, category=args.category, limit=args.limit)
    if args.json:
        print(json.dumps(ads, indent=2, ensure_ascii=False))
    else:
        format_results(ads, source)


def cmd_info(args):
    details = None
    url = f"https://api.leboncoin.fr/api/adfinder/v1/ad/{args.ad_id}"
    req = urllib.request.Request(url)
    req.add_header("api_key", LBC_API_KEY)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            details = json.loads(resp.read().decode())
    except Exception:
        pass

    if details:
        print(json.dumps(details, indent=2, ensure_ascii=False))
    else:
        print(f"[!] Could not fetch ad {args.ad_id} (Datadome — try from residential IP)")
        print(f"    https://www.leboncoin.fr/ad/item/{args.ad_id}")


def main():
    parser = argparse.ArgumentParser(prog="lbc", description="Leboncoin CLI scraper")
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("search", aliases=["s"], help="Search listings")
    sp.add_argument("query", help="Search query")
    sp.add_argument("--limit", "-n", type=int, default=20)
    sp.add_argument("--category", "-c", help="Category filter")
    sp.add_argument("--json", "-j", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp2 = sub.add_parser("info", aliases=["i"], help="Get ad details by ID")
    sp2.add_argument("ad_id")
    sp2.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
