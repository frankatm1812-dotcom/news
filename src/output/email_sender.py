"""Send briefing via 163 SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config_loader import get_env

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465


def send_email(subject: str, html_body: str) -> None:
    sender = get_env("SMTP_EMAIL")
    password = get_env("SMTP_PASSWORD")
    recipient = get_env("SMTP_RECIPIENT", sender)

    if not sender or not password:
        raise RuntimeError("SMTP_EMAIL and SMTP_PASSWORD must be set")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [recipient], msg.as_string())
        logger.info("Email sent to %s", recipient)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        raise
