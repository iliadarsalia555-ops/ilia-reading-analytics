
import os
import secrets
from pathlib import Path

from flask import Flask, redirect, render_template, session, url_for

import api
import auth
import database
from auth import login_required


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    default_db = Path(app.instance_path) / "reading.db"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("DATABASE_PATH") or str(default_db),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if test_config:
        app.config.update(test_config)

    # Set COOKIE_SECURE=1 on a real HTTPS production host.
    if os.environ.get("COOKIE_SECURE") == "1" and not app.config.get("TESTING"):
        app.config["SESSION_COOKIE_SECURE"] = True

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    database.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)

    @app.get("/")
    def index():
        if session.get("user_id"):
            return redirect(url_for("dashboard"))
        return redirect(url_for("auth.login"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
