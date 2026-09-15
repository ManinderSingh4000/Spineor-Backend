from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./candidates.db"
    upload_dir: Path = Path(__file__).resolve().parent / "uploads" / "resumes"
    max_resume_bytes: int = 5 * 1024 * 1024
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()


