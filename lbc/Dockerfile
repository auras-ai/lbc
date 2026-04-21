FROM python:3.12-slim AS base

# System deps for Playwright headless Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium runtime deps
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
    libx11-6 libxcb1 libxext6 libxfixes3 libexpat1 libdbus-1-3 \
    # Fonts so pages render text correctly
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy lockfile + project metadata first (layer cache)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

# Install Playwright Chromium (separate layer — big download, rarely changes)
RUN uv run playwright install chromium

# Copy source code
COPY src/ src/
COPY README.md ./
RUN uv sync --frozen

# Persistent browser profile (Datadome cookie + login session survive restarts)
VOLUME /data/lbc-profile
ENV XDG_DATA_HOME=/data

# Default: run the Telegram bot
CMD ["uv", "run", "lbc-bot"]
