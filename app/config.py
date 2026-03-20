from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GITNEXUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "gitnexus-py"
    log_level: str = Field(default="INFO", description="Logging level")

    data_dir: Path = Field(default=Path("./data"), description="BM25 indexes, caches")

    neo4j_uri: str | None = Field(default=None, description="e.g. bolt://localhost:7687")
    neo4j_user: str = "neo4j"
    neo4j_password: str = "gitnexus-dev"

    neo4j_enabled: bool = Field(
        default=True,
        description="If false, /ready skips DB; graph APIs return 503",
    )

    cypher_timeout_seconds: float = 30.0
    cypher_max_rows: int = 5000
    cypher_read_only: bool = True

    redis_url: str | None = Field(default=None, description="Optional, for future workers")


def get_settings() -> Settings:
    return Settings()
