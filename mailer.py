"""SMTP delivery of job applications to HR (BACKEND_PLAN.md §5). Stdlib only."""

import html
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from config import settings

log = logging.getLogger("mailer")

MIME_BY_EXT = {
    ".pdf": ("application", "pdf"),
    ".doc": ("application", "msword"),
    ".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


class EmailDeliveryError(Exception):
    pass


@dataclass
class ApplicationEmail:
    application_id: str
    job_id: int
    job_title: str
    first_name: str
    last_name: str
    email: str
    phone: str
    alternate_phone: str | None
    skills: str | None
    experience: str | None
    submitted_at_utc: str
    client_ip: str
    user_agent: str
    resume_path: Path
    resume_attachment_name: str


def _text_body(a: ApplicationEmail) -> str:
    lines = [
        f"Job: {a.job_title} (#{a.job_id})",
        f"Application ID: {a.application_id}",
        "",
        f"Name: {a.first_name} {a.last_name}",
        f"Email: {a.email}",
        f"Phone: {a.phone}",
        f"Alternate phone: {a.alternate_phone or '-'}",
        "",
        "Skills:",
        a.skills or "-",
        "",
        "Work experience:",
        a.experience or "-",
        "",
        f"Terms accepted: yes ({a.submitted_at_utc})",
        f"IP: {a.client_ip}",
        f"User-Agent: {a.user_agent}",
    ]
    return "\n".join(lines)


def _pre(value: str | None) -> str:
    return f"<pre style=\"white-space:pre-wrap\">{html.escape(value or '-')}</pre>"


def _html_body(a: ApplicationEmail) -> str:
    e = html.escape
    return f"""<html><body style="font-family:Arial,sans-serif;font-size:14px">
<h2>Job Application: {e(a.job_title)} (#{a.job_id})</h2>
<p><b>Application ID:</b> {e(a.application_id)}</p>
<table cellpadding="4">
<tr><td><b>Name</b></td><td>{e(a.first_name)} {e(a.last_name)}</td></tr>
<tr><td><b>Email</b></td><td><a href="mailto:{e(a.email)}">{e(a.email)}</a></td></tr>
<tr><td><b>Phone</b></td><td>{e(a.phone)}</td></tr>
<tr><td><b>Alternate phone</b></td><td>{e(a.alternate_phone or '-')}</td></tr>
</table>
<h3>Skills</h3>{_pre(a.skills)}
<h3>Work experience</h3>{_pre(a.experience)}
<p><b>Terms accepted:</b> yes ({e(a.submitted_at_utc)})</p>
<p style="color:#666;font-size:12px">IP: {e(a.client_ip)}<br>User-Agent: {e(a.user_agent)}</p>
</body></html>"""


def build_message(a: ApplicationEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Job Application: {a.job_title} (#{a.job_id}) - {a.first_name} {a.last_name}"
    msg["From"] = settings.email_from
    msg["To"] = settings.hr_email
    msg["Reply-To"] = a.email
    msg["X-Application-Id"] = a.application_id
    msg.set_content(_text_body(a))
    msg.add_alternative(_html_body(a), subtype="html")

    maintype, subtype = MIME_BY_EXT[a.resume_path.suffix.lower()]
    msg.add_attachment(
        a.resume_path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=a.resume_attachment_name,
    )
    return msg


def send_application(a: ApplicationEmail) -> None:
    """Send synchronously; raises EmailDeliveryError on any SMTP problem."""
    if not settings.smtp_configured:
        raise EmailDeliveryError("SMTP is not configured (SMTP_HOST / HR_EMAIL missing)")

    msg = build_message(a)
    try:
        if settings.smtp_secure:
            server = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
            )
        else:
            server = smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
            )
        with server:
            server.ehlo()
            if not settings.smtp_secure:
                try:
                    server.starttls()
                    server.ehlo()
                except smtplib.SMTPNotSupportedError:
                    log.warning("SMTP server does not support STARTTLS; sending unencrypted")
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        # Log the real reason server-side; the API returns a generic message.
        log.error("SMTP delivery failed for %s: %s", a.application_id, exc)
        raise EmailDeliveryError(str(exc)) from exc
