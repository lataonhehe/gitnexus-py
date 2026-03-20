from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pathspec

# Extensions we index in v1 (tree-sitter grammars can be added per language)
SOURCE_EXTENSIONS = {".py": "python"}


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
        rel_posix = rel.as_posix()
        if rel_posix.startswith(".git/") or rel.name == ".git":
            continue
        if gitignore and gitignore.match_file(rel_posix):
            continue
        ext = path.suffix.lower()
        if ext not in SOURCE_EXTENSIONS:
            continue
        yield path, SOURCE_EXTENSIONS[ext]
