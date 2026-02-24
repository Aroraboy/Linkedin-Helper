FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
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
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    dbus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m playwright install chromium && \
    python -m playwright install-deps chromium

# Copy application code
COPY . .

# Create a data directory for the SQLite DB
RUN mkdir -p /app/data

# Increase shared memory for Chromium (prevents "Page crashed" in containers)
RUN mkdir -p /dev/shm && chmod 1777 /dev/shm

# Environment — do NOT set PORT; Railway injects it dynamically
ENV SECRET_KEY=change-me-in-production
ENV DATABASE_URL=sqlite:////app/data/web_app.db
ENV PYTHONUNBUFFERED=1
ENV HEADLESS=true

EXPOSE 5000

# Use gunicorn with config file (reads PORT from env at runtime — no shell expansion needed)
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
