"""Delivery of job applications to HR (BACKEND_PLAN.md §5). Stdlib only.

Providers (EMAIL_PROVIDER): "smtp" for local dev, "brevo" or "resend" for production —
Render and most PaaS hosts block outbound SMTP ports, but HTTPS (443) always works.
"""

import base64
import html
import json
import logging
import smtplib
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
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


def _subject(a: ApplicationEmail) -> str:
    return f"Job Application: {a.job_title} (#{a.job_id}) - {a.first_name} {a.last_name}"


def _from_parts() -> tuple[str, str]:
    name, addr = parseaddr(settings.email_from)
    return name or "Spineor Careers", addr or settings.email_from


def _attachment_b64(a: ApplicationEmail) -> str:
    return base64.b64encode(a.resume_path.read_bytes()).decode("ascii")


def _http_post(url: str, headers: dict[str, str], payload: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.email_http_timeout_seconds) as resp:
            if resp.status >= 300:
                raise EmailDeliveryError(f"HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", "replace")
        raise EmailDeliveryError(f"HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EmailDeliveryError(str(exc)) from exc


def _send_brevo(a: ApplicationEmail) -> None:
    name, addr = _from_parts()
    _http_post(
        "https://api.brevo.com/v3/smtp/email",
        {"api-key": settings.brevo_api_key},
        {
            "sender": {"name": name, "email": addr},
            "to": [{"email": settings.hr_email}],
            "replyTo": {"email": a.email, "name": f"{a.first_name} {a.last_name}"},
            "subject": _subject(a),
            "htmlContent": _html_body(a),
            "textContent": _text_body(a),
            "attachment": [{"name": a.resume_attachment_name, "content": _attachment_b64(a)}],
            "headers": {"X-Application-Id": a.application_id},
        },
    )


def _send_resend(a: ApplicationEmail) -> None:
    _http_post(
        "https://api.resend.com/emails",
        {"Authorization": f"Bearer {settings.resend_api_key}"},
        {
            "from": settings.email_from,
            "to": [settings.hr_email],
            "reply_to": a.email,
            "subject": _subject(a),
            "html": _html_body(a),
            "text": _text_body(a),
            "attachments": [{"filename": a.resume_attachment_name, "content": _attachment_b64(a)}],
            "headers": {"X-Application-Id": a.application_id},
        },
    )


def _send_smtp(a: ApplicationEmail) -> None:
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
        raise EmailDeliveryError(str(exc)) from exc


_PROVIDERS = {"smtp": _send_smtp, "brevo": _send_brevo, "resend": _send_resend}


def send_application(a: ApplicationEmail) -> None:
    """Send synchronously via EMAIL_PROVIDER; raises EmailDeliveryError on any failure."""
    provider = settings.email_provider.lower()
    if provider not in _PROVIDERS:
        raise EmailDeliveryError(f"Unknown EMAIL_PROVIDER '{settings.email_provider}'")
    if not settings.email_configured:
        raise EmailDeliveryError(f"Email provider '{provider}' is not configured")
    try:
        _PROVIDERS[provider](a)
    except EmailDeliveryError as exc:
        # Log the real reason server-side; the API returns a generic message.
        log.error("%s delivery failed for %s: %s", provider, a.application_id, exc)
        raise
