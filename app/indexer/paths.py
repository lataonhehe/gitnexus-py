from __future__ import annotations

import hashlib
from pathlib import Path

import pathspec

from app.config import get_settings


def safe_repo_root(raw: str) -> Path:
    p = Path(raw).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise ValueError(f"Repository root is not a directory: {p}")
    allow = get_settings().repo_roots_allowlist
    if allow:
        roots = [Path(x).expanduser().resolve() for x in allow]
        if not any(p == r or r in p.parents for r in roots):
            raise ValueError(
                "Repository root is not under GITNEXUS_REPO_ROOTS_ALLOWLIST paths.",
            )
    return p


def load_gitignore_spec(root: Path) -> pathspec.PathSpec | None:
    gi = root / ".gitignore"
    if not gi.is_file():
        return None
    try:
        lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def is_ignored(rel_posix: str, spec: pathspec.PathSpec | None) -> bool:
    if spec is None:
        return False
    return spec.match_file(rel_posix)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
