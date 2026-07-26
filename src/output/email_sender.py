"""Send briefing via 163 SMTP."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config_loader import get_env

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
BEIJING_TZ = timezone(timedelta(hours=8))


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

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
    logger.info("Email sent to %s", recipient)


def send_failure_notification(error: str, traceback_text: str = "") -> None:
    """Notify recipient that the briefing pipeline failed."""
    now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    detail = traceback_text[-3000:] if traceback_text else "无详细堆栈"

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;max-width:720px;margin:0 auto;padding:20px;">
  <h1 style="color:#dc2626;">❌ 新闻简报生成失败</h1>
  <p style="color:#64748b;">{now} (北京时间)</p>
  <p>自动工作流运行时发生错误，本次简报<strong>未成功生成</strong>。</p>
  <h3>错误信息</h3>
  <pre style="background:#fef2f2;padding:12px;border-radius:6px;overflow-x:auto;">{error}</pre>
  <h3>详细信息</h3>
  <pre style="background:#f8fafc;padding:12px;border-radius:6px;font-size:12px;overflow-x:auto;">{detail}</pre>
  <p style="color:#94a3b8;font-size:12px;">
    请检查 GitHub Actions 日志，或本地运行 <code>python3 src/main.py --dry-run</code> 排查。
  </p>
</body>
</html>"""

    try:
        send_email(f"❌ 新闻简报失败 | {now}", html)
        logger.info("Failure notification sent")
    except Exception as exc:
        logger.error("Could not send failure notification: %s", exc)
