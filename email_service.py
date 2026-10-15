import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

SENDGRID_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"


def _sendgrid_configured():
    return bool(
        os.environ.get("SENDGRID_API_KEY")
        and os.environ.get("RESET_FROM_EMAIL")
    )


def send_password_reset_email(recipient, reset_url):
    """
    Send a password-reset link through the SendGrid HTTP API.

    Returns True when SendGrid accepts the message.
    In local development, PASSWORD_RESET_DEBUG=1 prints the link to the
    terminal instead of requiring an email provider.
    """
    if current_app.config.get("TESTING"):
        return True

    if os.environ.get("PASSWORD_RESET_DEBUG") == "1":
        current_app.logger.warning(
            "PASSWORD RESET DEBUG LINK for %s: %s", recipient, reset_url
        )
        return True

    if not _sendgrid_configured():
        current_app.logger.error(
            "Password reset email was requested, but SENDGRID_API_KEY "
            "or RESET_FROM_EMAIL is not configured."
        )
        return False

    api_key = os.environ["SENDGRID_API_KEY"]
    from_email = os.environ["RESET_FROM_EMAIL"].strip()
    from_name = os.environ.get("RESET_FROM_NAME", "Book Reading Analytics").strip()

    plain_text = (
        "A password reset was requested for your Book Reading Analytics account.\n\n"
        f"Reset your password here:\n{reset_url}\n\n"
        "This link expires in 30 minutes. If you did not request a reset, "
        "you can ignore this email."
    )

    html_text = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.55;color:#2b2f38">
      <h2>Reset your password</h2>
      <p>A password reset was requested for your Book Reading Analytics account.</p>
      <p>
        <a href="{reset_url}"
           style="display:inline-block;padding:10px 16px;background:#5b7fa6;
                  color:#fff;text-decoration:none;border-radius:6px">
          Reset password
        </a>
      </p>
      <p>This link expires in 30 minutes.</p>
      <p style="color:#6b7280;font-size:13px">
        If you did not request a reset, you can ignore this email.
      </p>
    </div>
    """.strip()

    payload = {
        "personalizations": [
            {
                "to": [{"email": recipient}],
                "subject": "Reset your Book Reading Analytics password",
            }
        ],
        "from": {"email": from_email, "name": from_name},
        "content": [
            {"type": "text/plain", "value": plain_text},
            {"type": "text/html", "value": html_text},
        ],
    }

    request = Request(
        SENDGRID_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=8) as response:
            # SendGrid normally returns HTTP 202 Accepted.
            return 200 <= response.status < 300
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        current_app.logger.error(
            "SendGrid rejected password reset email: HTTP %s %s",
            exc.code,
            detail[:500],
        )
    except (URLError, TimeoutError, OSError) as exc:
        current_app.logger.error("Password reset email could not be sent: %s", exc)

    return False
