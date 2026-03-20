from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pathspec

# Plan phase 2c — extended map; indexer v1 still walks only keys in SOURCE_EXTENSIONS.
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".rb": "ruby",
    ".cs": "c_sharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
}

IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "vendor",
}

# v1: Python only (tree-sitter grammars for other langs = future)
SOURCE_EXTENSIONS = {ext: lang for ext, lang in LANGUAGE_MAP.items() if lang == "python"}


def iter_indexable_files(
    root: Path,
    gitignore: pathspec.PathSpec | None,
) -> Iterator[tuple[Path, str]]:
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        if rel_posix.startswith(".git/") or rel.name == ".git":
            continue
        if gitignore and gitignore.match_file(rel_posix):
            continue
        ext = path.suffix.lower()
        if ext not in SOURCE_EXTENSIONS:
            continue
        yield path, SOURCE_EXTENSIONS[ext]
