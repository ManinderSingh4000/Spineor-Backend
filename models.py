import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


from database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    whatsapp: Mapped[str] = mapped_column(String(20), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    industry: Mapped[str] = mapped_column(String(255), nullable=False)
    experience: Mapped[str] = mapped_column(String(20), nullable=False)
    college: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_ctc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    skills_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(120), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resume_path: Mapped[str] = mapped_column(String(512), nullable=False)
    resume_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    @property
    def skills(self) -> list[str]:
        try:
            data = json.loads(self.skills_json)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
