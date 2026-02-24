"""
app.py — Flask application factory for LinkedIn Helper Web UI.

Run locally:
    python app.py

Environment variables:
    SECRET_KEY      — Flask secret key (auto-generated if not set)
    DATABASE_URL    — Database URI (default: sqlite:///web_app.db)
    PORT            — Port to run on (default: 5000)
"""

import os
import secrets
from pathlib import Path

from flask import Flask, redirect, url_for
from flask_login import LoginManager

from web.models import User, db
from web.auth import auth_bp
from web.dashboard import dashboard_bp


def create_app():
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )

    # ─── Config ───────────────────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///web_app.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

    # ─── Extensions ───────────────────────────────────────────────────────
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ─── Blueprints ───────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    # ─── Health check (for Railway / load balancers) ─────────────────
    @app.route("/health")
    def health():
        return "ok", 200
    # ─── Root redirect ────────────────────────────────────────────────────
    @app.route("/")
    def root():
        return redirect(url_for("dashboard.index"))

    # ─── Create tables ────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  LinkedIn Helper Web UI")
    print(f"  Running on http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
