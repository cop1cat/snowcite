from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None
    arxiv_delay: float = 3.0
    db_path: str = "data/papers.db"

    model_config = SettingsConfigDict(
        env_prefix="SNOWBALL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
