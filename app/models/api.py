from __future__ import annotations

import re
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, model_validator


def slug_from_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip().lower()).strip("-")
    return s or "repo"


class RepoCreate(BaseModel):
    """Register a repo (plan: path + name; optional explicit id)."""

    name: str = Field(..., min_length=1, max_length=256)
    path: str = Field(
        ...,
        validation_alias=AliasChoices("path", "root_path"),
        description="Absolute or relative path to repository root",
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    trigger_index: bool = Field(default=True, description="Run full index after register")


class RepoStats(BaseModel):
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0


class RepoListItem(BaseModel):
    id: str
    name: str
    root_path: str
    status: str | None = None
    indexed_at: str | None = None
    head_commit: str | None = None
    stats: RepoStats


class RepoListResponse(BaseModel):
    repos: list[RepoListItem]


class RepoOut(BaseModel):
    """Single-repo response (register / get)."""

    id: str
    name: str
    root_path: str
    status: str | None = None
    indexed_at: str | None = None
    head_commit: str | None = None
    stats: RepoStats | None = None


class IndexRequest(BaseModel):
    full: bool = Field(default=True, description="If true, replace existing graph for this repo")


class CypherRequest(BaseModel):
    query: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class CypherResponseV3(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False


class ContextRequestV3(BaseModel):
    name: str | None = None
    uid: str | None = None
    file_path: str | None = None
    depth: int = Field(default=1, ge=1, le=8)

    @model_validator(mode="after")
    def require_name_or_uid(self) -> ContextRequestV3:
        if not self.uid and not self.name:
            raise ValueError("Provide name and/or uid")
        return self


class ContextSymbolV3(BaseModel):
    uid: str
    name: str
    label: str
    signature: str = ""
    docstring: str = ""
    file_path: str
    start_line: int = 0
    end_line: int = 0


class ContextRefV3(BaseModel):
    uid: str
    name: str
    file_path: str
    label: str | None = None


class DefinedInV3(BaseModel):
    uid: str
    path: str


class ContextResponseV3(BaseModel):
    symbol: ContextSymbolV3 | None = None
    callers: list[ContextRefV3] = Field(default_factory=list)
    callees: list[ContextRefV3] = Field(default_factory=list)
    defined_in: DefinedInV3 | None = None
    disambiguation: list[ContextRefV3] = Field(default_factory=list)
    hint: str | None = None
