# Leboncoin CLI Scraper

`lbc` — Leboncoin search scraper combining multiple sources to bypass Datadome bot protection on datacenter/VPS IPs.

## Install

```bash
pip install urllib3  # stdlib only, no deps actually
sudo ln -s "$(pwd)/lbc.py" /usr/local/bin/lbc
```

## Usage

```bash
# Basic search
lbc search "rtx 3090"

# With category filter
lbc search "velo" -c sports_hobbies

# JSON output
lbc search "iphone 15" --json

# More results
lbc search "canape" -n 50

# Individual ad details (residential IP only)
lbc info 3175789654
```

## How It Works

Leboncoin uses Datadome protection that blocks all direct access from datacenter IPs (403 + captcha). This tool uses a 3-layer fallback strategy:

| Layer | Method | Data Provided | IP Required |
|-------|--------|--------------|-------------|
| 1 | Direct LBC API | Full details + prices, location, images | Residential only |
| 2 | Startpage (Google proxy) | Dates + descriptions | Any IP |
| 3 | DuckDuckGo HTML | Prices (sometimes) + snippets | Any IP |

Layers 2 and 3 are merged: Startpage provides the base (dates), DuckDuckGo enriches with prices when available.

## Categories

`voitures`, `motos`, `informatique`, `ordinateurs`, `accessoires_informatique`, `consoles`, `jeux_video`, `telephonie`, `image_son`, `electromenager`, `meubles`, `decoration`, `vetements`, `chaussures`, `sports_hobbies`, `musique`, `velos`, `immobilier`, `locations`, `services`

## Limitations

- No deep pagination (~20-30 results max per engine query)
- Dates are relative ("2 days ago", "18 hours ago")
- Direct API and `lbc info` only work from residential IP
- Prices may be missing when search engine snippets don't include them

## API Key

The `LBC_API_KEY` (`ba0c2dad52b3ec`) is Leboncoin's own public key embedded in their JavaScript. It is not a private credential.
