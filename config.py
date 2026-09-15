import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- legacy /api/candidates ---
    database_url: str = "sqlite:///./candidates.db"
    upload_dir: Path = Path(__file__).resolve().parent / "uploads" / "resumes"
    max_resume_bytes: int = 5 * 1024 * 1024
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://spineor-web-services.vercel.app"

    # --- /api/v1/job-applications (see BACKEND_PLAN.md §8) ---
    hr_email: str = "hrd@spineor.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_secure: bool = False  # True = implicit TLS (465); False = STARTTLS on 587
    smtp_timeout_seconds: int = 30
    email_from: str = "Spineor Careers <no-reply@spineor.com>"

    # 4 MB: Vercel serverless functions reject bodies over 4.5 MB before our code runs
    max_resume_size_bytes: int = 4 * 1024 * 1024
    # resume + multipart overhead + text fields; stays under Vercel's 4.5 MB cap
    max_request_body_bytes: int = int(4.4 * 1024 * 1024)
    # OS temp dir works on Vercel/Render where the project dir is read-only
    temp_upload_dir: Path = Path(tempfile.gettempdir()) / "spineor-resumes"

    cors_allowed_origins: str = (
        "http://localhost:5173,http://localhost:5174,"
        "https://spineortechnologies.com,https://www.spineortechnologies.com"
    )

    rate_limit_window_seconds: int = 600
    rate_limit_max_requests: int = 5

    # Job source of truth (§3, option 2). Empty ACTIVE_JOB_IDS = accept any positive id.
    active_job_ids: str = ""
    closed_job_ids: str = ""
    # Optional id -> title map, e.g. {"101": "Backend Engineer"}
    jobs_json: str = ""

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.hr_email)

    @staticmethod
    def split_csv(raw: str) -> list[str]:
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
