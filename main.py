import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from config import settings
from database import get_db, init_db
from job_applications import ENDPOINT_PATH, ApplicationError, error_payload
from job_applications import router as job_applications_router
from models import Candidate

from chatbot.schemas import ChatRequest, ChatResponse
from chatbot.session import get_or_create_session
from chatbot.state_machine import handle_message

# Typed as Literal so Swagger renders a dropdown and FastAPI rejects other values.
Gender = Literal["Male", "Female", "Other"]
Experience = Literal["Fresher", "0-1", "1-3", "3+"]
Source = Literal["LinkedIn", "Referral", "Website", "Other"]
WHATSAPP_RE = re.compile(r"^[6-9]\d{9}$")
CTC_RE = re.compile(r"^\d+(\.\d{1,2})?$")


def _parse_skills(raw: str | None) -> list[str]:
    if raw is None:
        raise HTTPException(
            status_code=422,
            detail='Missing form field "skills". Send JSON array text, e.g. ["Python","React"], or comma-separated skills.',
        )
    text = str(raw).strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail='Form field "skills" is empty. Use e.g. ["Python","React"] or Python, React',
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Postman/curl often send plain comma-separated text instead of JSON
        if "[" not in text and "]" not in text:
            parts = [p.strip() for p in text.split(",") if p.strip()]
            if parts:
                return parts
        raise HTTPException(
            status_code=422,
            detail=(
                f'Invalid skills: use a JSON array string like ["Python","React"] or comma-separated '
                f"values. ({e})"
            ),
        ) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise HTTPException(status_code=422, detail="skills must be a JSON array of strings")
    return [s.strip() for s in data if s and str(s).strip()]


def _validate_whatsapp(digits: str) -> str:
    d = re.sub(r"\D", "", digits or "")
    if not WHATSAPP_RE.match(d):
        raise HTTPException(
            status_code=422,
            detail="whatsapp must be a valid 10-digit Indian mobile number (starts with 6–9)",
        )
    return d


def _validate_candidate_fields(
    *,
    experience: str,
    college: str | None,
    current_ctc: str | None,
    skills: list[str],
) -> None:
    if experience == "Fresher":
        if not (college or "").strip() or len((college or "").strip()) < 2:
            raise HTTPException(status_code=422, detail="college is required for freshers")
    if current_ctc and str(current_ctc).strip():
        if not CTC_RE.match(str(current_ctc).strip()):
            raise HTTPException(
                status_code=422,
                detail="currentCTC must use numbers only (e.g. 8.5 for lakhs)",
            )
    if not skills:
        raise HTTPException(status_code=422, detail="Add at least one skill")


class CandidateCreated(BaseModel):
    id: int
    message: str = "Application received"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

APP_VERSION = "1.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.temp_upload_dir.mkdir(parents=True, exist_ok=True)
    # Legacy /api/candidates needs a writable dir + SQLite; on a read-only serverless
    # filesystem (Vercel) these fail, but the job-application route must still boot.
    try:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        init_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("Legacy candidate storage unavailable (%s); /api/candidates will fail", exc)
    if not settings.smtp_configured:
        log.warning("SMTP_HOST not set — POST %s will return 502 until it is configured", ENDPOINT_PATH)
    yield


app = FastAPI(title="Spineor backend API", version=APP_VERSION, lifespan=lifespan)

# Union of the legacy origins and the job-application origins (BACKEND_PLAN.md §9).
_origins = list(dict.fromkeys(
    settings.split_csv(settings.cors_origins) + settings.split_csv(settings.cors_allowed_origins)
))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

app.include_router(job_applications_router)


# --- error contract for /api/v1/job-applications (BACKEND_PLAN.md §6) ---

def _is_job_application(request: Request) -> bool:
    return request.url.path.rstrip("/") == ENDPOINT_PATH


@app.exception_handler(ApplicationError)
async def application_error_handler(_: Request, exc: ApplicationError):
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc.message, exc.errors))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    if not _is_job_application(request):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    errors: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", []) if p != "body"]
        errors[loc[-1] if loc else "request"] = "Invalid value."
    return JSONResponse(
        status_code=422,
        content=error_payload("Please correct the highlighted fields.", errors or None),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    if _is_job_application(request):
        return JSONResponse(
            status_code=500,
            content=error_payload(
                "We could not submit your application right now. Please try again later."
            ),
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# --- health ---

def _health_body() -> dict:
    return {
        "status": "ok",
        "service": "spineor-backend",
        "version": APP_VERSION,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "email_configured": settings.smtp_configured,
    }


@app.get("/health")
def health():
    return _health_body()


@app.get("/api/health")
def api_health():
    return _health_body()


@app.post("/api/candidates", response_model=CandidateCreated)
async def create_candidate(
    firstName: str = Form(..., min_length=1, max_length=120, examples=["Aarav"]),
    lastName: str = Form(..., min_length=1, max_length=120, examples=["Sharma"]),
    email: EmailStr = Form(..., examples=["aarav.sharma@example.com"]),
    whatsapp: str = Form(
        ..., description="10-digit Indian mobile number starting with 6-9", examples=["9876543210"]
    ),
    gender: Gender = Form(...),
    industry: str = Form(..., min_length=1, max_length=255, examples=["IT & Software"]),
    experience: Experience = Form(..., description="Years of experience. 'Fresher' requires college."),
    state: str = Form(..., min_length=1, max_length=120, examples=["Karnataka"]),
    city: str = Form(..., min_length=1, max_length=120, examples=["Bengaluru"]),
    source: Source = Form(..., description="How the candidate heard about us"),
    consent: bool = Form(..., description="Must be true"),
    skills: str = Form(
        ...,
        description='JSON array or comma-separated list, e.g. ["Python","React"] or Python, React',
        examples=["Python, React, SQL"],
    ),
    college: str | None = Form(None, max_length=255, description="Required when experience is Fresher"),
    currentCompany: str | None = Form(None, max_length=255),
    currentCTC: str | None = Form(None, description="Numbers only, in lakhs, e.g. 8.5", examples=["8.5"]),
    resumeFile: UploadFile = File(..., description="PDF only, max 5 MB"),
    db: Session = Depends(get_db),
):
    if not consent:
        raise HTTPException(status_code=422, detail="consent must be accepted")

    wa = _validate_whatsapp(whatsapp)
    skill_list = _parse_skills(skills)
    _validate_candidate_fields(
        experience=experience,
        college=college,
        current_ctc=currentCTC,
        skills=skill_list,
    )

    if not (firstName or "").strip() or not (lastName or "").strip():
        raise HTTPException(status_code=422, detail="first and last name are required")
    if not (industry or "").strip():
        raise HTTPException(status_code=422, detail="industry is required")
    if not (state or "").strip() or not (city or "").strip():
        raise HTTPException(status_code=422, detail="state and city are required")

    content_type = (resumeFile.content_type or "").lower()
    filename = resumeFile.filename or ""
    if "pdf" not in content_type and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF resumes are accepted")

    body = await resumeFile.read()
    if len(body) > settings.max_resume_bytes:
        raise HTTPException(status_code=422, detail="Resume must be under 5 MB")

    safe_stem = Path(filename).stem[:80] or "resume"
    stored_name = f"{uuid.uuid4().hex}_{safe_stem}.pdf"
    dest = settings.upload_dir / stored_name
    dest.write_bytes(body)

    row = Candidate(
        first_name=firstName.strip(),
        last_name=lastName.strip(),
        email=str(email).strip().lower(),
        whatsapp=wa,
        gender=gender,
        industry=industry.strip(),
        experience=experience,
        college=(college or "").strip() or None,
        current_company=(currentCompany or "").strip() or None,
        current_ctc=(currentCTC or "").strip() or None,
        skills_json=json.dumps(skill_list),
        state=state.strip(),
        city=city.strip(),
        source=source,
        consent=True,
        resume_path=str(dest.resolve()),
        resume_original_name=filename[:255],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return CandidateCreated(id=row.id)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id, session = get_or_create_session(request.session_id)

    response = handle_message(
        session=session,
        message=request.message,
        action_id=request.action_id,
    )

    return ChatResponse(
        session_id=session_id,
        reply=response["reply"],
        buttons=response["buttons"],
        input_enabled=response["input_enabled"],
    )
