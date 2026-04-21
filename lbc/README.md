# lbc — Leboncoin CLI (browser-emulated)

Full-research CLI for Leboncoin: paginated search, geo filters, clean prices &
ISO dates, single-ad details, plus a **messaging** layer to reply to sellers.
Works against Datadome because it drives a real Chromium via Playwright.

## Why a real browser

The previous `lbc.py` chained DuckDuckGo / Startpage fallbacks because the raw
`api.leboncoin.fr/finder/search` endpoint is behind Datadome and blocks every
datacenter IP. Those fallbacks gave partial, noisy data (no prices or rough
dates at best).

Leboncoin's `/recherche` page is **server-rendered with Next.js App Router**
and streams the full search payload as RSC (React Server Component) chunks.
Those chunks accumulate in the page's `self.__next_f` array, and concatenating
them yields a blob containing a `"searchData":{...}` object identical in shape
to what the old Pages-Router `__NEXT_DATA__` exposed:

```
props.pageProps.searchData.ads[i] = {
  list_id, subject, body, url,
  first_publication_date, index_date,                # real ISO timestamps
  price: [2300], price_cents: 230000,
  category_id, category_name,
  location: { city, zipcode, department_name, region_name, lat, lng },
  owner: { name, user_id, store_id, type: "private"|"pro" },
  images: { thumb_url, small_url, urls_large: [...] },
  attributes: [{ key, value_label }, ...],
  ...
}
```

So the strategy becomes: **drive a real Chromium** (so Datadome is satisfied),
navigate to the URL, wait for the RSC stream to arrive, read `self.__next_f`
from inside the page, and bracket-match the `searchData` JSON out of it. A
DOM-scrape fallback covers the (rare) case where the stream key name drifts.

> We previously tried calling `https://api.leboncoin.fr/finder/search` directly
> via in-browser `fetch()`. Datadome now 403s that endpoint for browser
> callers — it's become mobile-only. The SSR-stream path is the only reliable
> shape as of April 2026.

### Browser engine chosen

| Engine | Verdict |
|---|---|
| **Playwright / Chromium (persistent context)** | Chosen. Real TLS + JS, Datadome-compatible, persistent profile keeps the cookie solved, same flow covers login/messaging. |
| curl_cffi (Chrome TLS fingerprint) | Fast, but breaks on JS challenges; no path to messaging. |
| [lightpanda-io/browser](https://github.com/lightpanda-io/browser) | Promising — a ~10x lighter Zig headless browser. It doesn't yet run the full Datadome JS bundle reliably, and has no first-class Python binding. Worth swapping in later as a faster backend once it matures; the `BrowserSession` class is the only place that'd change. |

## Install

```bash
cd lbc
uv sync
uv run playwright install chromium
# Optional — expose as `lbc` on PATH:
uv tool install --editable .
```

## First run

```bash
lbc login          # headful browser opens; sign in once
lbc whoami         # verifies the saved session
```

Subsequent commands run headless and reuse the session + Datadome cookie.

## Usage

```bash
# The exact URL you gave as input, via the CLI:
lbc search imac --lat 43.33935 --lng -0.69070 --radius 100000 \
                --sort time --order desc -n 100

# Other examples:
lbc search "rtx 3090" -n 50 --category informatique --price-max 800
lbc search "vélo électrique" --category sports_hobbies --owner private --json
lbc search "canapé" --lat 48.8566 --lng 2.3522 --radius 20000 -n 200

# Inspect what URL would be hit (no browser launched):
lbc search imac --lat 43.33 --lng -0.69 --radius 100000 --show-url

# Single-ad details (full body, attributes, images):
lbc info 3140748683
lbc info 3140748683 --json

# Messaging (requires `lbc login` first):
lbc inbox -n 20
lbc send "https://www.leboncoin.fr/ad/ordinateurs/3140748683" "Bonjour, toujours dispo ?"
lbc send "<ad-url>" "test" --dry-run    # fills the form but doesn't click Send
```

## Flags

| Flag | Meaning |
|---|---|
| `-n / --limit` | Max results across all pages (auto-paginates). |
| `-p / --page` | Starting page. |
| `--category` | Slug (see list below) or numeric id. |
| `--lat / --lng / --radius` | Geo search (radius in meters). |
| `--sort time\|relevance\|price` | Sort key. |
| `--order asc\|desc` |   |
| `--price-min / --price-max` | Price range in EUR. |
| `--owner private\|pro\|all` | Seller type filter. |
| `-j / --json` | Emit JSON (full normalized record). |
| `--headed` | Show the browser — useful for debugging. |

## JSON record shape

```jsonc
{
  "id": "3140748683",
  "title": "Lot de 2 IMac Pro 27 pouces",
  "url": "https://www.leboncoin.fr/ad/ordinateurs/3140748683",
  "price": 2300,
  "price_cents": 230000,
  "buyer_fee_cents": 99,
  "category_id": "15",
  "category_name": "Ordinateurs",
  "published_at": "2026-02-07T08:34:27",
  "indexed_at": "2026-02-07T08:34:27",
  "published_relative": "il y a 2 mois",
  "body": "...",
  "location": { "city": "Capbreton", "zipcode": "40130", "department": "Landes", "region": "Aquitaine", "lat": 43.64, "lng": -1.43 },
  "owner":    { "name": "Barouillet", "user_id": "525e...", "store_id": "6809463", "type": "private" },
  "is_pro": false,
  "images": [ "https://img.leboncoin.fr/..." ],
  "thumb":  "https://img.leboncoin.fr/...",
  "attributes": { "estimated_parcel_weight": "16391", "estimated_parcel_size": "M" },
  "has_phone": false,
  "status": null
}
```

## Where is my session stored?

```bash
lbc where
```

Delete that directory to fully log out and reset Datadome.

## Categories

`voitures`, `motos`, `informatique`, `ordinateurs`, `accessoires_informatique`,
`consoles`, `jeux_video`, `telephonie`, `image_son`, `electromenager`,
`meubles`, `decoration`, `vetements`, `chaussures`, `sports_hobbies`,
`musique`, `velos`, `immobilier`, `locations`, `services`.

## Notes

* Be gentle. Leboncoin rate-limits; pagination runs sequentially and one
  Chromium context reuses the same cookie, which is what they expect.
* Messaging uses UI automation rather than a reverse-engineered chat API —
  more robust across Leboncoin's frequent A/B tests.
* Never commit the profile directory: it contains an auth cookie tied to
  your account.
