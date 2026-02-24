"""
models.py — SQLAlchemy models for the web app.

Tables:
    - User: Authentication + per-user settings
    - Job: A batch connection/message job
    - JobProfile: Individual profile in a job
"""

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Registered user with their own LinkedIn session."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # Per-user LinkedIn session cookie (JSON string)
    linkedin_session = db.Column(db.Text, nullable=True)

    # Per-user templates
    connection_note = db.Column(
        db.Text,
        default="Hi {first_name}, I'd love to connect with you!",
    )
    followup_message = db.Column(
        db.Text,
        default="Thanks for connecting, {first_name}! Looking forward to staying in touch.",
    )

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    jobs = db.relationship("Job", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def has_linkedin_session(self) -> bool:
        return bool(self.linkedin_session)


class Job(db.Model):
    """A batch automation job (connect / message / both)."""

    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    mode = db.Column(db.String(20), nullable=False, default="connect")  # connect | message | both
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | running | completed | failed | cancelled

    total_profiles = db.Column(db.Integer, default=0)
    processed = db.Column(db.Integer, default=0)
    sent = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)
    errors = db.Column(db.Integer, default=0)

    # CSV filename (stored in user_data/<user_id>/)
    csv_filename = db.Column(db.String(256), nullable=True)

    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Current status message for live updates
    live_status = db.Column(db.String(500), default="Waiting to start...")

    profiles = db.relationship(
        "JobProfile", backref="job", lazy=True, cascade="all, delete-orphan"
    )


class JobProfile(db.Model):
    """Individual LinkedIn profile within a job."""

    __tablename__ = "job_profiles"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False)

    url = db.Column(db.String(500), nullable=False)
    name = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending")
    # pending | request_sent | already_connected | already_pending | skipped | error | messaged
    error_msg = db.Column(db.String(500), nullable=True)

    processed_at = db.Column(db.DateTime, nullable=True)
