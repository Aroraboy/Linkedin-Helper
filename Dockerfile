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

# Create a data directory for the SQLite DB (persistent volume mount point)
RUN mkdir -p /data

# Environment
ENV PORT=5000
ENV SECRET_KEY=change-me-in-production
ENV DATABASE_URL=sqlite:////data/web_app.db
ENV PYTHONUNBUFFERED=1
ENV HEADLESS=true

EXPOSE 5000

# Use gunicorn with enough timeout for Playwright operations
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "600", "wsgi:app"]
