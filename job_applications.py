"""POST /api/v1/job-applications — see BACKEND_PLAN.md.

Flow (§11): body-size guard -> rate limit -> parse multipart -> validate job ->
validate text fields (collect all errors) -> validate + temp-save resume ->
email HR with attachment -> delete temp file (always) -> 201 JSON.
"""

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status

from config import settings
from jobs import lookup_job
from mailer import ApplicationEmail, EmailDeliveryError, send_application
from rate_limit import RateLimiter

log = logging.getLogger("job_applications")

router = APIRouter(prefix="/api/v1", tags=["job-applications"])
ENDPOINT_PATH = "/api/v1/job-applications"

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
ALLOWED_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # browsers send these for .doc/.docx on some platforms; magic bytes decide
    "application/octet-stream",
    "",
}
MAGIC = {
    ".pdf": (b"%PDF-",),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".docx": (b"PK\x03\x04",),
}
PHONE_RE = re.compile(r"^\+?[\d\s()\-]{7,20}$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")

MSG_VALIDATION = "Please correct the highlighted fields."
MSG_TOO_LARGE = f"Resume must be {settings.max_resume_size_bytes // (1024 * 1024)} MB or smaller."
MSG_RATE_LIMITED = "Too many attempts. Please wait a moment and try again."
MSG_JOB_CLOSED = "This job is no longer accepting applications."
MSG_JOB_UNKNOWN = "This job is no longer available."
MSG_SERVER = "We could not submit your application right now. Please try again later."
MSG_RESUME_TYPE = "Only PDF, DOC, and DOCX files are allowed."

_limiter = RateLimiter(settings.rate_limit_max_requests, settings.rate_limit_window_seconds)


class ApplicationError(Exception):
    """Carries the §6 error contract; rendered by the handler in main.py."""

    def __init__(self, status_code: int, message: str, errors: dict[str, str] | None = None):
        self.status_code = status_code
        self.message = message
        self.errors = errors
        super().__init__(message)


def error_payload(message: str, errors: dict[str, str] | None = None) -> dict:
    body: dict = {"success": False, "message": message}
    if errors:
        body["errors"] = errors
    return body


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _guard(request: Request) -> None:
    """Runs before the multipart body is parsed (§11 steps 1-2)."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_request_body_bytes:
        raise ApplicationError(413, MSG_TOO_LARGE, {"resume": MSG_TOO_LARGE})
    if not _limiter.allow(client_ip(request)):
        raise ApplicationError(429, MSG_RATE_LIMITED)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _validate_text_fields(
    *,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    alternate_phone: str,
    skills: str,
    experience: str,
    accept_terms: str,
) -> dict[str, str]:
    errors: dict[str, str] = {}

    if not 1 <= len(first_name) <= 100:
        errors["first_name"] = "First name is required (max 100 characters)."
    if not 1 <= len(last_name) <= 100:
        errors["last_name"] = "Family name is required (max 100 characters)."

    if not email:
        errors["email"] = "Email address is required."
    else:
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            errors["email"] = "Enter a valid email address."

    if not phone:
        errors["phone"] = "Phone number is required."
    elif not PHONE_RE.match(phone) or len(re.sub(r"\D", "", phone)) < 7:
        errors["phone"] = "Enter a valid phone number."

    if alternate_phone and (
        not PHONE_RE.match(alternate_phone) or len(re.sub(r"\D", "", alternate_phone)) < 7
    ):
        errors["alternate_phone"] = "Enter a valid alternate phone number."

    if len(skills) > 2000:
        errors["skills"] = "Skills must be 2000 characters or fewer."
    if len(experience) > 5000:
        errors["experience"] = "Work experience must be 5000 characters or fewer."

    if accept_terms.lower() != "true":
        errors["accept_terms"] = "You must accept the terms to apply."

    return errors


async def _save_resume(resume: UploadFile | None, errors: dict[str, str]) -> Path | None:
    """Validate ext/MIME/magic/size and stream to TEMP_UPLOAD_DIR/<uuid>.<ext>.

    Adds to `errors` on validation failure; raises ApplicationError(413) on size.
    Returns the temp path (caller must delete it) or None if invalid.
    """
    if resume is None or not resume.filename:
        errors["resume"] = "Resume is required."
        return None

    ext = Path(resume.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        errors["resume"] = MSG_RESUME_TYPE
        return None
    if (resume.content_type or "").lower() not in ALLOWED_MIME:
        errors["resume"] = MSG_RESUME_TYPE
        return None

    settings.temp_upload_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.temp_upload_dir / f"{uuid.uuid4().hex}{ext}"

    size = 0
    head = b""
    try:
        with dest.open("wb") as fh:
            while chunk := await resume.read(64 * 1024):
                if len(head) < 8:
                    head += chunk[: 8 - len(head)]
                size += len(chunk)
                if size > settings.max_resume_size_bytes:
                    raise ApplicationError(413, MSG_TOO_LARGE, {"resume": MSG_TOO_LARGE})
                fh.write(chunk)
    except ApplicationError:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await resume.close()

    if size == 0 or not any(head.startswith(m) for m in MAGIC[ext]):
        dest.unlink(missing_ok=True)
        errors["resume"] = MSG_RESUME_TYPE
        return None

    return dest


def _attachment_name(last: str, first: str, job_id: int, ext: str) -> str:
    safe = lambda s: SAFE_NAME_RE.sub("", s.replace(" ", "_"))[:40] or "Candidate"  # noqa: E731
    return f"{safe(last)}_{safe(first)}_{job_id}{ext}"


@router.options("/job-applications", include_in_schema=False)
def job_applications_preflight() -> Response:
    # CORSMiddleware normally answers this; kept so a direct OPTIONS still returns 204.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/job-applications", status_code=status.HTTP_201_CREATED, dependencies=[Depends(_guard)])
async def create_job_application(
    request: Request,
    # All declared Optional[str] on purpose: multipart carries only strings, and a missing
    # field must surface as errors.<field> (BACKEND_PLAN.md §6), not FastAPI's default 422.
    job_id: str | None = Form(None, description="Numeric id of the job (required)", examples=["102"]),
    job_title: str | None = Form(None, description="Informational only", examples=["Frontend Engineer"]),
    first_name: str | None = Form(None, description="Required, 1-100 chars", examples=["Aarav"]),
    last_name: str | None = Form(None, description="Required, 1-100 chars", examples=["Sharma"]),
    email: str | None = Form(None, description="Required, valid email", examples=["aarav@example.com"]),
    phone: str | None = Form(None, description="Required, 7-20 chars: digits + - ( ) space", examples=["+91 98765 43210"]),
    alternate_phone: str | None = Form(None, description="Optional, same format as phone"),
    skills: str | None = Form(None, description="Optional free text, max 2000 chars", examples=["React, TypeScript"]),
    experience: str | None = Form(None, description="Optional free text, max 5000 chars", examples=["3 years building SPAs"]),
    accept_terms: str | None = Form(None, description='Must be "true"', examples=["true"]),
    resume: UploadFile | None = File(None, description="Required: .pdf, .doc or .docx, max 4 MB"),
):
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:512]

    # §11.4 job validation
    job_id_raw = _clean(job_id)
    if not job_id_raw.isdigit() or int(job_id_raw) <= 0:
        await _discard(resume)
        raise ApplicationError(422, MSG_VALIDATION, {"job_id": "A valid job id is required."})
    job_id_int = int(job_id_raw)
    job_status, resolved_title = lookup_job(job_id_int, _clean(job_title)[:200])
    if job_status == "closed":
        await _discard(resume)
        raise ApplicationError(410, MSG_JOB_CLOSED)
    if job_status == "unknown":
        await _discard(resume)
        raise ApplicationError(404, MSG_JOB_UNKNOWN)

    # §11.5 text fields — collect every error
    fields = {
        "first_name": _clean(first_name),
        "last_name": _clean(last_name),
        "email": _clean(email),
        "phone": _clean(phone),
        "alternate_phone": _clean(alternate_phone),
        "skills": _clean(skills),
        "experience": _clean(experience),
        "accept_terms": _clean(accept_terms),
    }
    errors = _validate_text_fields(**fields)

    # §11.6 resume
    temp_path: Path | None = None
    try:
        temp_path = await _save_resume(resume, errors)
        if errors:
            raise ApplicationError(422, MSG_VALIDATION, errors)
        assert temp_path is not None

        # §11.7-8 email
        application_id = f"app_{uuid.uuid4().hex[:12]}"
        submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = ApplicationEmail(
            application_id=application_id,
            job_id=job_id_int,
            job_title=resolved_title,
            first_name=fields["first_name"],
            last_name=fields["last_name"],
            email=fields["email"],
            phone=fields["phone"],
            alternate_phone=fields["alternate_phone"] or None,
            skills=fields["skills"] or None,
            experience=fields["experience"] or None,
            submitted_at_utc=submitted_at,
            client_ip=ip,
            user_agent=user_agent,
            resume_path=temp_path,
            resume_attachment_name=_attachment_name(
                fields["last_name"], fields["first_name"], job_id_int, temp_path.suffix
            ),
        )
        email_hash = hashlib.sha256(fields["email"].lower().encode()).hexdigest()[:12]
        try:
            send_application(payload)
        except EmailDeliveryError:
            log.warning(
                "application=%s job=%s email_hash=%s ip=%s outcome=email_failed",
                application_id, job_id_int, email_hash, ip,
            )
            raise ApplicationError(502, MSG_SERVER)

        log.info(
            "application=%s job=%s email_hash=%s ip=%s outcome=submitted",
            application_id, job_id_int, email_hash, ip,
        )
        return {
            "success": True,
            "message": "Your application has been submitted successfully.",
            "data": {"application_id": application_id, "job_id": job_id_int, "status": "submitted"},
        }
    finally:
        # §11.9 — never keep the resume
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


async def _discard(resume: UploadFile | None) -> None:
    if resume is not None:
        await resume.close()
