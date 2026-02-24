"""
dashboard.py — Main dashboard blueprint (upload, jobs, settings, progress).
"""

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session as flask_session,
    stream_with_context,
    url_for,
    jsonify,
)
from flask_login import current_user, login_required

from web.forms import (
    LinkedInLoginForm,
    LinkedInSessionForm,
    LinkedInVerifyForm,
    SettingsForm,
    UploadForm,
)
from web.linkedin_auth import login_to_linkedin, submit_verification_code
from web.models import Job, JobProfile, User, db
from web.worker import cancel_job, start_job

dashboard_bp = Blueprint("dashboard", __name__)

# Regex for validating LinkedIn profile URLs
LINKEDIN_URL_RE = re.compile(
    r"https?://(www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?", re.IGNORECASE
)


@dashboard_bp.route("/")
@login_required
def index():
    """Main dashboard — list all jobs."""
    jobs = (
        Job.query.filter_by(user_id=current_user.id)
        .order_by(Job.created_at.desc())
        .all()
    )
    return render_template("dashboard/index.html", jobs=jobs)


@dashboard_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Upload CSV and create a new job."""
    if not current_user.has_linkedin_session():
        flash("Please configure your LinkedIn session first.", "warning")
        return redirect(url_for("dashboard.settings"))

    form = UploadForm()
    if form.validate_on_submit():
        file = form.csv_file.data
        mode = form.mode.data
        filename = file.filename.lower()

        # Extract URLs from CSV or Excel/Google Sheets (.xlsx)
        try:
            urls = []

            if filename.endswith((".xlsx", ".xls")):
                # Excel / Google Sheets export
                wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
                for sheet in wb.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        for cell in row:
                            if cell:
                                cell_str = str(cell).strip()
                                if LINKEDIN_URL_RE.match(cell_str):
                                    urls.append(cell_str)
                wb.close()
            else:
                # CSV / TXT
                content = file.read().decode("utf-8-sig")
                reader = csv.reader(io.StringIO(content))
                for row in reader:
                    for cell in row:
                        cell = cell.strip()
                        if LINKEDIN_URL_RE.match(cell):
                            urls.append(cell)

            if not urls:
                flash("No valid LinkedIn URLs found in the file.", "error")
                return render_template("dashboard/upload.html", form=form)

            # Create job
            job = Job(
                user_id=current_user.id,
                mode=mode,
                total_profiles=len(urls),
                csv_filename=file.filename,
            )
            db.session.add(job)
            db.session.flush()  # Get job.id

            # Create profile entries
            for url in urls:
                profile = JobProfile(job_id=job.id, url=url)
                db.session.add(profile)

            db.session.commit()

            flash(f"Job created with {len(urls)} profiles!", "success")
            return redirect(url_for("dashboard.job_detail", job_id=job.id))

        except Exception as e:
            flash(f"Error reading CSV: {e}", "error")
            return render_template("dashboard/upload.html", form=form)

    return render_template("dashboard/upload.html", form=form)


@dashboard_bp.route("/job/<int:job_id>")
@login_required
def job_detail(job_id):
    """View a specific job and its profiles."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    profiles = JobProfile.query.filter_by(job_id=job_id).all()
    return render_template("dashboard/job.html", job=job, profiles=profiles)


@dashboard_bp.route("/job/<int:job_id>/start", methods=["POST"])
@login_required
def start(job_id):
    """Start processing a job."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()

    if job.status in ("running",):
        flash("Job is already running.", "warning")
        return redirect(url_for("dashboard.job_detail", job_id=job_id))

    # Reset if re-running
    if job.status in ("completed", "failed", "cancelled"):
        job.processed = 0
        job.sent = 0
        job.skipped = 0
        job.errors = 0
        job.status = "pending"
        job.live_status = "Restarting..."
        # Reset errored profiles to pending
        JobProfile.query.filter_by(job_id=job_id, status="error").update(
            {"status": "pending", "error_msg": None}
        )
        db.session.commit()

    start_job(current_app._get_current_object(), job_id, headless=request.form.get("browser_mode") == "headless")
    flash("Job started!", "success")
    return redirect(url_for("dashboard.job_detail", job_id=job_id))


@dashboard_bp.route("/job/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel(job_id):
    """Cancel a running job."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    if job.status == "running":
        job.status = "cancelled"
        db.session.commit()
        flash("Job cancellation requested.", "info")
    return redirect(url_for("dashboard.job_detail", job_id=job_id))


@dashboard_bp.route("/job/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job(job_id):
    """Delete a job and all its profiles."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    if job.status == "running":
        flash("Cannot delete a running job. Cancel it first.", "warning")
        return redirect(url_for("dashboard.job_detail", job_id=job_id))

    db.session.delete(job)
    db.session.commit()
    flash("Job deleted.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/job/<int:job_id>/progress")
@login_required
def job_progress(job_id):
    """API endpoint returning job progress as JSON (polled by frontend)."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    return jsonify(
        {
            "status": job.status,
            "processed": job.processed,
            "total": job.total_profiles,
            "sent": job.sent,
            "skipped": job.skipped,
            "errors": job.errors,
            "live_status": job.live_status,
            "percent": round(job.processed / job.total_profiles * 100)
            if job.total_profiles
            else 0,
        }
    )


@dashboard_bp.route("/job/<int:job_id>/export")
@login_required
def export_job(job_id):
    """Export job results as CSV download."""
    job = Job.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    profiles = JobProfile.query.filter_by(job_id=job_id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Name", "Status", "Error", "Processed At"])
    for p in profiles:
        writer.writerow([p.url, p.name or "", p.status, p.error_msg or "", p.processed_at or ""])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=job_{job_id}_results.csv"},
    )


@dashboard_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """User settings — templates + LinkedIn session."""
    settings_form = SettingsForm(
        connection_note=current_user.connection_note,
        followup_message=current_user.followup_message,
    )
    session_form = LinkedInSessionForm()
    login_form = LinkedInLoginForm()
    verify_form = LinkedInVerifyForm()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_templates" and settings_form.validate_on_submit():
            current_user.connection_note = settings_form.connection_note.data
            current_user.followup_message = settings_form.followup_message.data
            db.session.commit()
            flash("Templates saved!", "success")

        elif action == "save_session" and session_form.validate_on_submit():
            try:
                # Validate it's valid JSON
                json.loads(session_form.session_json.data)
                current_user.linkedin_session = session_form.session_json.data
                db.session.commit()
                flash("LinkedIn session saved!", "success")
            except json.JSONDecodeError:
                flash("Invalid JSON. Please paste the full contents of state.json.", "error")

        return redirect(url_for("dashboard.settings"))

    return render_template(
        "dashboard/settings.html",
        settings_form=settings_form,
        session_form=session_form,
        login_form=login_form,
        verify_form=verify_form,
    )


@dashboard_bp.route("/settings/linkedin-login", methods=["POST"])
@login_required
def linkedin_login():
    """Handle LinkedIn credential login."""
    login_form = LinkedInLoginForm()

    if login_form.validate_on_submit():
        email = login_form.li_email.data
        password = login_form.li_password.data

        flash("Logging into LinkedIn... This may take a moment.", "info")
        result = login_to_linkedin(email, password)

        if result["success"]:
            current_user.linkedin_session = result["session_json"]
            db.session.commit()
            flash("Successfully logged into LinkedIn! Session saved.", "success")
            return redirect(url_for("dashboard.settings"))

        if result["needs_verification"]:
            # Store intermediate state in Flask session for the verify step
            flask_session["li_intermediate_state"] = result.get("intermediate_state")
            flash(
                "LinkedIn requires a verification code. Check your email/phone and enter it below.",
                "warning",
            )
            return redirect(url_for("dashboard.settings", verify=1))

        # Login error
        flash(f"LinkedIn login failed: {result['error']}", "error")
    else:
        for field, errors in login_form.errors.items():
            for err in errors:
                flash(f"{err}", "error")

    return redirect(url_for("dashboard.settings"))


@dashboard_bp.route("/settings/linkedin-verify", methods=["POST"])
@login_required
def linkedin_verify():
    """Handle LinkedIn 2FA / verification code submission."""
    verify_form = LinkedInVerifyForm()

    if verify_form.validate_on_submit():
        intermediate_state = flask_session.get("li_intermediate_state")

        if not intermediate_state:
            flash("No pending verification. Please log in again.", "error")
            return redirect(url_for("dashboard.settings"))

        code = verify_form.verification_code.data.strip()
        result = submit_verification_code(intermediate_state, code)

        if result["success"]:
            current_user.linkedin_session = result["session_json"]
            db.session.commit()
            flask_session.pop("li_intermediate_state", None)
            flash("Verification successful! LinkedIn session saved.", "success")
            return redirect(url_for("dashboard.settings"))

        if result["needs_verification"]:
            flash(
                result.get("error", "Wrong code. Please try again."),
                "error",
            )
            return redirect(url_for("dashboard.settings", verify=1))

        flash(f"Verification failed: {result['error']}", "error")
        flask_session.pop("li_intermediate_state", None)
    else:
        for field, errors in verify_form.errors.items():
            for err in errors:
                flash(f"{err}", "error")

    return redirect(url_for("dashboard.settings"))
