from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

ENV_FILE_PATH = BASE_DIR.parent / ".env.dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_user: str
    postgres_password: str
    postgres_host: str
    pgport: int
    postgres_db: str

    celery_broker_url: str

    storage_dir: Path = BASE_DIR / "storage" / "files"

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.pgport}/{self.postgres_db}"
        )


settings = Settings()

settings.storage_dir.mkdir(parents=True, exist_ok=True)
