"""Gunicorn config — reads PORT from environment (Railway sets this dynamically)."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 1
threads = 4
timeout = 600
loglevel = "info"
accesslog = "-"
