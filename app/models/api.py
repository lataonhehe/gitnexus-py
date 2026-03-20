from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RepoCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(..., min_length=1, max_length=256)
    root_path: str = Field(..., description="Absolute or relative path to repository root")


class RepoOut(BaseModel):
    id: str
    name: str
    root_path: str
    indexed_at: str | None = None
    head_commit: str | None = None


class IndexRequest(BaseModel):
    full: bool = Field(default=True, description="If true, replace existing graph for this repo")


class CypherRequest(BaseModel):
    query: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class CypherResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool = False


class ContextRequest(BaseModel):
    repo_id: str
    name: str | None = None
    uid: str | None = None
    file_path: str | None = None
    max_depth: int = Field(default=2, ge=1, le=8)


class ContextMatch(BaseModel):
    uid: str
    name: str
    kind: str
    file_path: str
    qualified_name: str | None = None


class ContextResponse(BaseModel):
    disambiguation: list[ContextMatch] = Field(default_factory=list)
    selected: ContextMatch | None = None
    callers: list[dict[str, Any]] = Field(default_factory=list)
    callees: list[dict[str, Any]] = Field(default_factory=list)
    imports: list[dict[str, Any]] = Field(default_factory=list)
    imported_by: list[dict[str, Any]] = Field(default_factory=list)
