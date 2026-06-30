FROM python:3.12-slim

WORKDIR /app

# System dependencies required by Playwright (used by Crawl4AI for JS-rendered pages)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser (used by Crawl4AI)
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# Create directories that will be mounted as volumes
RUN mkdir -p /app/db /app/logs /app/config

CMD ["python", "scheduler.py"]
