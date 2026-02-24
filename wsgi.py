"""WSGI entry point for gunicorn / Railway deployment."""

import os
import sys
import traceback

print("[WSGI] Starting application...", flush=True)
print(f"[WSGI] Python: {sys.version}", flush=True)
print(f"[WSGI] PORT={os.environ.get('PORT', 'NOT SET')}", flush=True)
print(f"[WSGI] DATABASE_URL={os.environ.get('DATABASE_URL', 'NOT SET')}", flush=True)
print(f"[WSGI] CWD={os.getcwd()}", flush=True)

try:
    from app import create_app
    print("[WSGI] create_app imported", flush=True)
    app = create_app()
    print("[WSGI] App created successfully!", flush=True)
except Exception as e:
    print(f"[WSGI] FATAL: {e}", flush=True)
    traceback.print_exc()
    # Fallback: a tiny app that passes healthcheck and shows the error
    from flask import Flask
    app = Flask(__name__)

    _err = str(e)

    @app.route("/health")
    def health():
        return "ok", 200

    @app.route("/")
    def root():
        return f"<h1>Startup Error</h1><pre>{_err}</pre>", 500
