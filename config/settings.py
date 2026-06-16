from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # LinkedIn
    linkedin_email: str = ""
    linkedin_password: str = ""

    # Indeed
    indeed_email: str = ""
    indeed_password: str = ""

    # Glassdoor
    glassdoor_email: str = ""
    glassdoor_password: str = ""

    # User profile
    user_full_name: str = "Applicant"
    user_email: str = ""
    user_phone: str = ""
    user_location: str = "New York, NY"
    user_linkedin_url: str = ""
    user_github_url: str = ""
    user_portfolio_url: str = ""

    # Paths
    db_path: Path = Path("data/jobs.db")
    resume_dir: Path = Path("data/resumes")
    sessions_dir: Path = Path("data/sessions")

    # Scraping behaviour
    linkedin_delay_min: float = 4.0
    linkedin_delay_max: float = 9.0
    max_jobs_per_source: int = 50

    # Application behaviour
    dry_run: bool = False


settings = Settings()
