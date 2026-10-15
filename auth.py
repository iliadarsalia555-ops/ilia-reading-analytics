import hashlib
import hmac
import os
import sqlite3
from functools import wraps

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db
from email_service import send_password_reset_email

bp = Blueprint("auth", __name__)


RESET_SALT = "book-reading-analytics-password-reset-v1"
RESET_MAX_AGE_SECONDS = 30 * 60


def _password_fingerprint(password_hash):
    """Short fingerprint used to invalidate old reset links after a password change."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:24]


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=RESET_SALT)


def create_password_reset_token(user):
    return _reset_serializer().dumps({
        "uid": user["id"],
        "pwd": _password_fingerprint(user["password_hash"]),
    })


def validate_password_reset_token(token):
    try:
        data = _reset_serializer().loads(
            token,
            max_age=RESET_MAX_AGE_SECONDS,
        )
    except (SignatureExpired, BadSignature):
        return None

    user_id = data.get("uid")
    expected_fingerprint = data.get("pwd")
    if not user_id or not expected_fingerprint:
        return None

    user = get_db().execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if user is None:
        return None

    actual_fingerprint = _password_fingerprint(user["password_hash"])
    if not hmac.compare_digest(actual_fingerprint, expected_fingerprint):
        # Password changed after the token was issued, so the token is obsolete.
        return None

    return user


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if session.get("user_id") is None:
            # Browser pages redirect to login; fetch/API calls receive a real 401 JSON response.
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("auth.login"))
        return view(**kwargs)
    return wrapped_view


@bp.route("/register", methods=("GET", "POST"))
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        error = None
        if len(username) < 3 or len(username) > 40:
            error = "Username must contain 3–40 characters."
        elif len(email) > 120 or "@" not in email or "." not in email.split("@")[-1]:
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must contain at least 8 characters."

        if error is None:
            db = get_db()
            try:
                cursor = db.execute(
                    """INSERT INTO users(username, email, password_hash)
                       VALUES (?, ?, ?)""",
                    (username, email, generate_password_hash(password)),
                )
                db.commit()
                session.clear()
                session["user_id"] = cursor.lastrowid
                session["username"] = username
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError as exc:
                db.rollback()
                text = str(exc).lower()
                if "username" in text:
                    error = "That username is already registered."
                elif "email" in text:
                    error = "That email address is already registered."
                else:
                    error = "That account already exists."

        flash(error, "error")

    return render_template("register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            """SELECT * FROM users
               WHERE username = ? COLLATE NOCASE
                  OR email = ? COLLATE NOCASE""",
            (identity, identity),
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect username/email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))

    return render_template("login.html")


@bp.route("/forgot-password", methods=("GET", "POST"))
def forgot_password():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        # Always show the same result so the page does not reveal whether
        # an email address is registered.
        user = None
        if email:
            user = get_db().execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()

        if user is not None:
            token = create_password_reset_token(user)
            public_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
            if public_base_url:
                reset_path = url_for("auth.reset_password", token=token)
                reset_url = f"{public_base_url}{reset_path}"
            else:
                # Locally this preserves http://127.0.0.1:5000.
                # On a correctly configured HTTPS host it uses the request scheme.
                reset_url = url_for(
                    "auth.reset_password",
                    token=token,
                    _external=True,
                )
            send_password_reset_email(user["email"], reset_url)

        return render_template(
            "forgot_password.html",
            submitted=True,
        )

    return render_template("forgot_password.html", submitted=False)


@bp.route("/reset-password/<token>", methods=("GET", "POST"))
def reset_password(token):
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    user = validate_password_reset_token(token)
    if user is None:
        return render_template(
            "reset_password.html",
            invalid_token=True,
            token=token,
        ), 400

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        error = None
        if len(password) < 8:
            error = "Password must contain at least 8 characters."
        elif password != confirm_password:
            error = "The two passwords do not match."

        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), user["id"]),
            )
            db.commit()

            # The password hash changed, so the token used above and all
            # previously issued reset links are now automatically invalid.
            session.clear()
            flash("Password updated. You can now log in with your new password.", "success")
            return redirect(url_for("auth.login"))

    return render_template(
        "reset_password.html",
        invalid_token=False,
        token=token,
    )


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
