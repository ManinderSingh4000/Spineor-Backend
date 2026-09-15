import json
import re
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from config import settings
from database import get_db, init_db
from models import Candidate


from chatbot.schemas import ChatRequest, ChatResponse
from chatbot.session import get_or_create_session
from chatbot.state_machine import handle_message

ALLOWED_GENDER = {"Male", "Female", "Other"}
ALLOWED_EXPERIENCE = {"Fresher", "0-1", "1-3", "3+"}
ALLOWED_SOURCE = {"LinkedIn", "Referral", "Website", "Other"}
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


app = FastAPI(title="Candidate intake API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/candidates", response_model=CandidateCreated)
async def create_candidate(
    firstName: str = Form(...),
    lastName: str = Form(...),
    email: EmailStr = Form(...),
    whatsapp: str = Form(...),
    gender: str = Form(...),
    industry: str = Form(...),
    experience: str = Form(...),
    state: str = Form(...),
    city: str = Form(...),
    source: str = Form(...),
    consent: str = Form(...),
    skills: str = Form(...),
    college: str | None = Form(None),
    currentCompany: str | None = Form(None),
    currentCTC: str | None = Form(None),
    resumeFile: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if gender not in ALLOWED_GENDER:
        raise HTTPException(status_code=422, detail="Invalid gender")
    if experience not in ALLOWED_EXPERIENCE:
        raise HTTPException(status_code=422, detail="Invalid experience")
    if source not in ALLOWED_SOURCE:
        raise HTTPException(status_code=422, detail="Invalid source")
    consent_lower = (consent or "").lower()
    if consent_lower not in ("true", "1", "yes", "on"):
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
