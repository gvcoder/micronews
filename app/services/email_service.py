"""Simple SMTP email helper.

Reads configuration from environment variables:
  SMTP_HOST      — SMTP server hostname
  SMTP_PORT      — SMTP server port (default: 587)
  SMTP_USER      — SMTP login username
  SMTP_PASSWORD  — SMTP login password
  SMTP_FROM      — From address (falls back to SMTP_USER)

If SMTP_HOST is not set the function logs a warning and returns without
raising, so the rest of the application continues to work in environments
where email is not configured (e.g. development / CI).
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email.

    Args:
        to:      Recipient email address.
        subject: Email subject line.
        body:    Plain-text email body.
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not smtp_host:
        logger.warning(
            "SMTP_HOST is not configured — skipping email to %s (subject: %s)",
            to,
            subject,
        )
        return

    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, [to], msg.as_string())
        logger.info("Email sent to %s (subject: %s)", to, subject)
    except Exception as exc:
        logger.error(
            "Failed to send email to %s (subject: %s): %s", to, subject, exc
        )
