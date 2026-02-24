"""
worker.py — Background worker that runs the LinkedIn bot for a job.

Each job runs in a separate thread. The worker updates the Job and
JobProfile rows in the database so the dashboard can show live progress.
"""

import json
import re
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from web.models import Job, JobProfile, User, db as _db


# Global dict to track running threads: {job_id: Thread}
_running_jobs: dict[int, Thread] = {}


def start_job(app, job_id: int):
    """Launch a background thread to process a job."""
    if job_id in _running_jobs and _running_jobs[job_id].is_alive():
        return  # Already running

    t = Thread(target=_run_job, args=(app, job_id), daemon=True)
    _running_jobs[job_id] = t
    t.start()


def cancel_job(job_id: int):
    """Signal a job to stop (checked between profiles)."""
    # We use a simple flag on the Job.status column
    pass  # The worker loop checks job.status == "cancelled"


def _run_job(app, job_id: int):
    """
    Main worker loop — runs inside a background thread.
    Uses the app context to access the database.
    """
    # Import bot here to avoid circular imports
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from linkedin_bot import LinkedInBot, LinkedInCapReachedError

    with app.app_context():
        job = _db.session.get(Job, job_id)
        if not job:
            return

        user = _db.session.get(User, job.user_id)
        if not user or not user.linkedin_session:
            job.status = "failed"
            job.live_status = "No LinkedIn session configured. Go to Settings."
            _db.session.commit()
            return

        # Update job status
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.live_status = "Starting browser..."
        _db.session.commit()

        bot = None
        try:
            # Write user's session to a temp file
            session_path = Path(tempfile.mktemp(suffix=".json"))
            session_path.write_text(user.linkedin_session, encoding="utf-8")

            # Launch the bot — headless in production (no display), headed locally
            import os
            is_production = os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RENDER") or os.environ.get("HEADLESS", "").lower() == "true"
            bot = LinkedInBot(state_path=str(session_path), headless=is_production)
            bot.start()

            if not bot.is_logged_in():
                job.status = "failed"
                job.live_status = "LinkedIn session expired. Please update in Settings."
                _db.session.commit()
                return

            job.live_status = "Browser ready. Processing profiles..."
            _db.session.commit()

            # Get all pending profiles for this job
            profiles = JobProfile.query.filter_by(job_id=job_id, status="pending").all()
            job.total_profiles = len(profiles)
            _db.session.commit()

            for i, profile in enumerate(profiles):
                # Check if job was cancelled
                _db.session.refresh(job)
                if job.status == "cancelled":
                    job.live_status = "Job cancelled by user."
                    _db.session.commit()
                    break

                job.live_status = f"[{i+1}/{len(profiles)}] Processing {profile.url}..."
                _db.session.commit()

                try:
                    if job.mode in ("connect", "both"):
                        # Always send without a note for connect mode
                        result = bot.send_connection_request(
                            profile.url, send_note=False
                        )
                        profile.status = result
                        if result == "request_sent":
                            job.sent += 1
                        elif result in ("already_connected", "already_pending"):
                            job.skipped += 1
                        elif result == "skipped":
                            job.skipped += 1
                        elif result == "cap_reached":
                            job.live_status = "LinkedIn weekly cap reached. Stopping."
                            profile.status = "skipped"
                            job.skipped += 1
                            _db.session.commit()
                            break
                        else:
                            job.errors += 1

                    if job.mode in ("message", "both"):
                        if job.mode == "both" and profile.status != "already_connected":
                            pass  # Skip messaging if not connected
                        else:
                            msg_template = user.followup_message or "Thanks for connecting, {first_name}!"
                            result = bot.send_followup_message(profile.url, msg_template)
                            profile.status = result
                            if result == "messaged":
                                job.sent += 1
                            elif result == "error":
                                job.errors += 1
                            else:
                                job.skipped += 1

                except LinkedInCapReachedError:
                    profile.status = "skipped"
                    job.skipped += 1
                    job.live_status = "LinkedIn weekly cap reached. Stopping."
                    _db.session.commit()
                    break
                except Exception as e:
                    profile.status = "error"
                    profile.error_msg = str(e)[:500]
                    job.errors += 1

                profile.processed_at = datetime.now(timezone.utc)
                job.processed += 1
                name = profile.name or profile.url.split("/in/")[-1].strip("/")
                job.live_status = f"[{i+1}/{len(profiles)}] Done: {name} → {profile.status}"
                _db.session.commit()

                # Delay between profiles (shorter for web)
                if i < len(profiles) - 1:
                    import random
                    time.sleep(random.uniform(8, 15))

            # Job complete
            if job.status != "cancelled":
                job.status = "completed"
                job.live_status = f"Done! Sent: {job.sent}, Skipped: {job.skipped}, Errors: {job.errors}"
            job.completed_at = datetime.now(timezone.utc)
            _db.session.commit()

        except Exception as e:
            job.status = "failed"
            job.live_status = f"Error: {str(e)[:300]}"
            job.completed_at = datetime.now(timezone.utc)
            _db.session.commit()
            traceback.print_exc()

        finally:
            if bot:
                try:
                    bot.close()
                except Exception:
                    pass
            # Clean up temp session file
            try:
                session_path.unlink(missing_ok=True)
            except Exception:
                pass
