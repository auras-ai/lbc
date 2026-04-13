FROM python:3.12-slim

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock .python-version ./
COPY src/ src/

# Install deps + playwright browsers
RUN uv sync --frozen \
    && uv run playwright install chromium

# Persistent browser profile volume
VOLUME /data/lbc-profile

ENV LBC_HEADLESS=true
ENV PLATFORMDIRS_HOME=/data

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "lbc.api:app", "--host", "0.0.0.0", "--port", "8000"]
