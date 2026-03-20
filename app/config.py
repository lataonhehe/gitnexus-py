from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_allowlist(v: str | list[str] | None) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [p.strip() for p in str(v).split(",") if p.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GITNEXUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server (plan P1 + uvicorn CLI can still override host/port)
    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("HOST", "GITNEXUS_HOST"))
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT", "GITNEXUS_PORT"))

    app_name: str = "gitnexus-py"
    log_level: str = Field(default="INFO", description="Logging level")

    data_dir: Path = Field(default=Path("./data"), description="BM25 indexes, caches")

    neo4j_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NEO4J_URI", "GITNEXUS_NEO4J_URI"),
        description="e.g. bolt://localhost:7687",
    )
    neo4j_user: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("NEO4J_USER", "GITNEXUS_NEO4J_USER"),
    )
    neo4j_password: str = Field(
        default="gitnexus-dev",
        validation_alias=AliasChoices("NEO4J_PASSWORD", "GITNEXUS_NEO4J_PASSWORD"),
    )
    neo4j_database: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("NEO4J_DATABASE", "GITNEXUS_NEO4J_DATABASE"),
    )

    neo4j_enabled: bool = Field(
        default=True,
        description="If false, /ready skips DB; graph APIs return 503",
    )

    repo_roots_allowlist: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("REPO_ROOTS_ALLOWLIST", "GITNEXUS_REPO_ROOTS_ALLOWLIST"),
        description="If non-empty, repo roots must resolve under one of these paths",
    )

    cypher_timeout_seconds: float = 30.0
    cypher_max_rows: int = 1000
    cypher_read_only: bool = True

    redis_url: str | None = Field(default=None, description="Optional, for future workers")

    # Git URL → clone under DATA_DIR/clones/{repo_id}
    git_clone_depth: int = Field(default=1, ge=1, le=500, description="git clone --depth")
    git_clone_timeout_seconds: int = Field(
        default=600,
        ge=30,
        le=7200,
        description="Timeout for git clone/pull (seconds)",
    )
    git_binary: str = Field(default="git", description="git executable name/path")
    git_url_allowed_hosts: list[str] = Field(
        default_factory=list,
        description="If non-empty, clone URL host must match (e.g. github.com, *.gitlab.com)",
    )

    @field_validator("repo_roots_allowlist", mode="before")
    @classmethod
    def _split_allowlist(cls, v: str | list[str] | None) -> list[str]:
        return _parse_allowlist(v)

    @field_validator("git_url_allowed_hosts", mode="before")
    @classmethod
    def _split_git_hosts(cls, v: str | list[str] | None) -> list[str]:
        return _parse_allowlist(v)


def get_settings() -> Settings:
    return Settings()
