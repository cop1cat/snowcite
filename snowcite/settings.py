from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global settings derived from env (`SNOWCITE_*`).

    Project-specific state (database path, metadata, etc.) is resolved per-call
    via `snowcite.projects` — it lives in `<project>/.snowcite/`, not here.
    """

    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None
    arxiv_delay: float = 3.0

    model_config = SettingsConfigDict(
        env_prefix="SNOWCITE_",
        extra="ignore",
    )


settings = Settings()
