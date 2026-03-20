from __future__ import annotations

import re
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, model_validator


def slug_from_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip().lower()).strip("-")
    return s or "repo"


class RepoCreate(BaseModel):
    """Register a repo: either local `path` or remote `git_url` (clone then index)."""

    name: str = Field(..., min_length=1, max_length=256)
    path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("path", "root_path"),
        description="Local filesystem path to repository root (mutually exclusive with git_url)",
    )
    git_url: str | None = Field(
        default=None,
        description="https(s) clone URL (GitHub, GitLab, …); cloned under server data/clones/{id}",
    )
    branch: str | None = Field(
        default=None,
        max_length=256,
        description="Optional branch for git clone (default branch if omitted)",
    )
    force_clone: bool = Field(
        default=False,
        description="If true and git_url: delete existing worktree and clone fresh",
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    trigger_index: bool = Field(default=True, description="Run full index after register")

    @model_validator(mode="after")
    def path_xor_git_url(self) -> RepoCreate:
        p = (self.path or "").strip()
        g = (self.git_url or "").strip()
        if bool(p) == bool(g):
            raise ValueError("Provide exactly one of: path (or root_path), or git_url")
        object.__setattr__(self, "path", p or None)
        object.__setattr__(self, "git_url", g or None)
        return self


class RepoStats(BaseModel):
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0


class RepoListItem(BaseModel):
    id: str
    name: str
    root_path: str
    git_url: str | None = None
    git_branch: str | None = None
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
    git_url: str | None = None
    git_branch: str | None = None
    status: str | None = None
    indexed_at: str | None = None
    head_commit: str | None = None
    stats: RepoStats | None = None


class IndexRequest(BaseModel):
    full: bool = Field(default=True, description="If true, replace existing graph for this repo")
    pull: bool = Field(
        default=False,
        description="If repo was registered with git_url, run git pull --ff-only before index",
    )


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
