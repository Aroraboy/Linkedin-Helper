"""
forms.py — WTForms for the web app.
"""

from flask_wtf import FlaskForm
from wtforms import (
    FileField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class RegisterForm(FlaskForm):
    username = StringField(
        "Username", validators=[DataRequired(), Length(min=3, max=80)]
    )
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(min=6)]
    )
    confirm = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )


class UploadForm(FlaskForm):
    csv_file = FileField("CSV File with LinkedIn URLs", validators=[DataRequired()])
    mode = SelectField(
        "Mode",
        choices=[
            ("connect", "Send Connection Requests"),
            ("message", "Send Follow-up Messages"),
            ("both", "Connect + Message"),
        ],
        default="connect",
    )


class SettingsForm(FlaskForm):
    connection_note = TextAreaField(
        "Connection Note Template",
        validators=[DataRequired(), Length(max=300)],
        description="Use {first_name} as placeholder. Max 300 chars.",
    )
    followup_message = TextAreaField(
        "Follow-up Message Template",
        validators=[DataRequired(), Length(max=2000)],
        description="Use {first_name} as placeholder.",
    )


class LinkedInSessionForm(FlaskForm):
    session_json = TextAreaField(
        "LinkedIn Session (JSON)",
        validators=[DataRequired()],
        description="Paste the contents of your state.json file here.",
    )


class LinkedInLoginForm(FlaskForm):
    """Login to LinkedIn with email & password."""
    li_email = StringField(
        "LinkedIn Email",
        validators=[DataRequired(), Email()],
    )
    li_password = PasswordField(
        "LinkedIn Password",
        validators=[DataRequired()],
    )


class LinkedInVerifyForm(FlaskForm):
    """Enter LinkedIn verification / 2FA code."""
    verification_code = StringField(
        "Verification Code",
        validators=[DataRequired(), Length(min=4, max=10)],
    )
