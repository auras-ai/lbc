# lbc — Deployment & Usage Guide

Leboncoin CLI + Telegram bot + optional REST API.  
Browser-emulated scraping via Playwright Chromium with persistent profile to bypass Datadome anti-bot protection.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [CLI Usage](#cli-usage)
4. [Telegram Bot](#telegram-bot)
5. [REST API (optional)](#rest-api-optional)
6. [Docker Deployment](#docker-deployment)
7. [Server Deployment (VPS)](#server-deployment-vps)
8. [Datadome & Anti-Bot Considerations](#datadome--anti-bot-considerations)
9. [Troubleshooting](#troubleshooting)
10. [Environment Variables](#environment-variables)

---

## Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)
- A residential IP for the initial browser login (datacenter IPs get challenged)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather)) if using the bot

---

## Local Development Setup

```bash
# Clone the repo
git clone git@github.com:auras-ai/lbc.git
cd lbc

# Install dependencies + Playwright Chromium
uv sync
uv run playwright install chromium

# Sign in to Leboncoin (opens a visible browser window)
uv run lbc login

# Verify login persists
uv run lbc whoami
# → "logged in"
```

The browser profile (cookies, Datadome token, login session) is saved to:

```bash
uv run lbc where
# macOS: ~/Library/Application Support/lbc/chromium-profile
# Linux: ~/.local/share/lbc/chromium-profile
```

---

## CLI Usage

### Search

```bash
# Basic search
uv run lbc search "imac" -n 20

# Geo-filtered search around Pau, 100 km radius
uv run lbc search "rtx 4090" --lat 43.34 --lng -0.69 --radius 100000

# Category + price filter + JSON output
uv run lbc search "vélo électrique" --category velos --price-max 1500 --json

# YAML output
uv run lbc search "iphone 15" --yaml

# Show the resolved Leboncoin URL without searching
uv run lbc search "canapé" --show-url

# Debug mode: dump raw HTML to a directory for inspection
uv run lbc search "test" --debug ./debug-output
```

**Search flags:**

| Flag | Description |
|------|-------------|
| `-n`, `--limit` | Max results (default 35) |
| `-p`, `--page` | Starting page (default 1) |
| `-c`, `--category` | Category slug (informatique, ameublement, velos, etc.) |
| `--lat`, `--lng`, `--radius` | Geo filter (lat/lng in decimal, radius in meters) |
| `--sort` | time, relevance, or price (default time) |
| `--order` | asc or desc (default desc) |
| `--price-min`, `--price-max` | Price range in euros |
| `--owner` | private, pro, or all |
| `-f`, `--format` | pretty, json, or yaml |
| `-j`, `--json` | Shortcut for `--format json` |
| `-y`, `--yaml` | Shortcut for `--format yaml` |
| `--headed` | Show the browser window (debug) |
| `--debug DIR` | Dump raw HTML + scripts for inspection |
| `--show-url` | Print the URL and exit |

### Ad Details

```bash
# By ad ID
uv run lbc info 3140748683

# JSON output
uv run lbc info 3140748683 --json
```

### Messaging

```bash
# Sign in first
uv run lbc login

# Send a message to a seller
uv run lbc send "https://www.leboncoin.fr/ad/informatique/3140748683.htm" "Bonjour, est-ce toujours disponible ?"

# Dry run (fill the form but don't click send)
uv run lbc send "https://www.leboncoin.fr/ad/..." "Bonjour" --dry-run
```

### Inbox

```bash
uv run lbc inbox -n 10
uv run lbc inbox --json
```

### Other

```bash
uv run lbc where      # Print browser profile path
uv run lbc whoami     # Check login status
uv run lbc --version  # Print version
```

---

## Telegram Bot

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Copy the token into `.env`:

```bash
cp .env.example .env  # or create manually
echo 'TELEGRAM_BOT_TOKEN=your_token_here' > .env
```

3. Start the bot:

```bash
uv run lbc-bot
```

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + usage |
| `/search <query>` | Search Leboncoin |
| `/s <query>` | Alias for /search |
| `/info <ad_id>` | Full ad details + first image |
| `/msg <url> <text>` | Send a message to a seller |
| `/cybex` | List saved Cybex Bouncer results |
| `/help` | Show help |

**Inline filters** (append to /search):

```
/search rtx 4090 max:800 cat:informatique n:15
/search vélo min:200 max:1000 owner:private
/s canapé geo:43.34,-0.69,50000 n:20
```

| Filter | Example | Description |
|--------|---------|-------------|
| `max:<price>` | `max:800` | Maximum price |
| `min:<price>` | `min:50` | Minimum price |
| `cat:<slug>` | `cat:informatique` | Category |
| `n:<limit>` | `n:20` | Max results (default 10) |
| `geo:<lat>,<lng>,<radius>` | `geo:43.34,-0.69,100000` | Location filter |
| `owner:<type>` | `owner:private` | private or pro |

Plain text messages (no `/` prefix) are treated as search queries automatically.

---

## REST API (optional)

A FastAPI service is included but commented out in `docker-compose.yml`.

```bash
# Run locally
uv run uvicorn lbc.api:app --host 0.0.0.0 --port 8000

# Health check
curl http://localhost:8000/health
```

To enable in Docker, uncomment the `api` service in `docker-compose.yml`.

---

## Docker Deployment

### Build and Run

```bash
# Build the image
docker compose build

# Create .env with your bot token
echo 'TELEGRAM_BOT_TOKEN=your_token_here' > .env

# Start the bot
docker compose up -d

# View logs
docker compose logs -f bot

# Stop
docker compose down
```

### Volumes

The container uses a named Docker volume `lbc-profile` mounted at `/data/lbc/chromium-profile` to persist the browser profile (login session + Datadome cookie) across container restarts.

The `cybex_results.yml` file is bind-mounted read-only so the `/cybex` bot command works.

### First Login in Docker

The container runs headless by default. For the initial Leboncoin login, you have two options:

**Option A — Login locally, copy profile into the volume:**

```bash
# Login locally (opens a browser window)
uv run lbc login

# Find your local profile
uv run lbc where
# e.g. ~/.local/share/lbc/chromium-profile

# Copy into the Docker volume
docker compose up -d bot
docker compose cp ~/.local/share/lbc/chromium-profile bot:/data/lbc/chromium-profile
docker compose restart bot
```

**Option B — Login via a temporary headed container (requires X11/VNC):**

```bash
# On a machine with a display:
docker compose run --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
  bot uv run lbc login
```

---

## Server Deployment (VPS)

### Minimum Requirements

- 1 vCPU, 1 GB RAM (2 GB recommended for concurrent searches)
- 2 GB disk (Chromium + profile)
- Docker + Docker Compose installed
- A residential IP or proxy for the initial login

### Step-by-Step

```bash
# 1. SSH into your server
ssh user@your-server

# 2. Clone the repo
git clone git@github.com:auras-ai/lbc.git
cd lbc

# 3. Create .env
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=your_token_here
EOF

# 4. Build and start
docker compose up -d --build

# 5. Check it's running
docker compose logs -f bot
```

### systemd Service (alternative to Docker)

If you prefer running without Docker:

```ini
# /etc/systemd/system/lbc-bot.service
[Unit]
Description=Leboncoin Telegram Bot
After=network.target

[Service]
Type=simple
User=lbc
WorkingDirectory=/opt/lbc
EnvironmentFile=/opt/lbc/.env
ExecStart=/usr/local/bin/uv run lbc-bot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Install and start
sudo cp lbc-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lbc-bot
sudo journalctl -u lbc-bot -f
```

### Enabling the REST API on a Server

Uncomment the `api` service in `docker-compose.yml`, then put it behind a reverse proxy:

```nginx
# /etc/nginx/sites-available/lbc-api
server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Datadome & Anti-Bot Considerations

Leboncoin uses **Datadome** for bot protection. Key points:

1. **Residential IP required for initial login.** Datacenter IPs (AWS, OVH, Hetzner) are flagged instantly. Run `lbc login` from your home machine or use a residential proxy.

2. **Persistent profile is critical.** The Chromium profile stores the Datadome cookie. Once solved, subsequent headless requests reuse it. If you wipe the profile, you need to re-login.

3. **Cookie expiry.** The Datadome cookie expires periodically (typically a few days). If searches start failing, re-run `lbc login` from a residential IP.

4. **Server workaround.** Login locally, copy the profile directory to the server (see Docker section above). The cookie remains valid from the server IP for a while. If it expires, you'll need to re-login locally and re-copy.

5. **Rate limiting.** Avoid hammering Leboncoin. The bot's default limit of 10 results per search is reasonable. Aggressive scraping will trigger Datadome challenges.

6. **Stealth flags.** The browser session already sets `--disable-blink-features=AutomationControlled` and removes the `navigator.webdriver` flag.

---

## Troubleshooting

### "error: couldn't find 'searchData' in RSC stream"

The RSC extraction failed. Possible causes:

- Datadome cookie expired — run `lbc login` again
- Leboncoin changed their page structure — use `--debug ./dump` to inspect raw HTML
- Network issue — retry

### "error: ... returned 403"

Datadome blocked the request. Re-login from a residential IP.

### "not logged in" when using /msg or /send

Run `lbc login` in a headed browser first. The session is stored in the profile directory.

### Empty search results

- Check that the query returns results on leboncoin.fr manually
- Try with `--headed` to see if Datadome shows a challenge page
- Use `--debug ./dump` and inspect the HTML files

### Bot not responding on Telegram

- Verify the token in `.env` matches your bot
- Check logs: `docker compose logs bot` or `journalctl -u lbc-bot`
- Ensure only one instance is running (Telegram only delivers updates to one poller)

### Docker volume issues

```bash
# Inspect the profile volume
docker volume inspect lbc_lbc-profile

# Reset the profile (forces re-login)
docker compose down
docker volume rm lbc_lbc-profile
docker compose up -d
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes (for bot) | Token from @BotFather |
| `XDG_DATA_HOME` | No | Override profile storage location (default: OS-standard) |
| `LBC_PORT` | No | API port when using docker-compose (default: 8000) |
