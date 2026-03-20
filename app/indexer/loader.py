from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from neo4j import Driver

from app.db.neo4j_client import ensure_constraints, run_read, run_write
from app.indexer.paths import file_sha256, load_gitignore_spec, safe_repo_root
from app.indexer.python_parse import parse_python_file
from app.indexer.walker import iter_indexable_files

logger = logging.getLogger(__name__)


def _delete_repo_graph(driver: Driver, repo_id: str) -> None:
    """Remove indexed nodes for a repo; keep the :Repo registration node."""
    run_write(
        driver,
        """
        MATCH (n {repo_id: $repo_id})
        DETACH DELETE n
        """,
        {"repo_id": repo_id},
    )


def _ensure_folder_chain(driver: Driver, repo_id: str, rel_file_posix: str) -> None:
    parts = Path(rel_file_posix).parts
    if len(parts) <= 1:
        return
    parent_parts = parts[:-1]
    prev_uid: str | None = None
    for i in range(len(parent_parts)):
        path = "/".join(parent_parts[: i + 1])
        uid = f"{repo_id}:{path}"
        name = parent_parts[i]
        run_write(
            driver,
            """
            MERGE (f:Folder {uid: $uid})
            SET f.repo_id = $repo_id, f.path = $path, f.name = $name
            """,
            {"uid": uid, "repo_id": repo_id, "path": path, "name": name},
        )
        if prev_uid is None:
            run_write(
                driver,
                """
                MATCH (r:Repo {id: $repo_id})
                MATCH (f:Folder {uid: $uid})
                MERGE (r)-[:CONTAINS]->(f)
                """,
                {"repo_id": repo_id, "uid": uid},
            )
        else:
            run_write(
                driver,
                """
                MATCH (p:Folder {uid: $prev})
                MATCH (c:Folder {uid: $uid})
                MERGE (p)-[:CONTAINS]->(c)
                """,
                {"prev": prev_uid, "uid": uid},
            )
        prev_uid = uid


def _link_file_to_parent_folder(
    driver: Driver,
    repo_id: str,
    file_uid: str,
    rel_posix: str,
) -> None:
    parent = str(Path(rel_posix).parent.as_posix())
    if parent in ("", "."):
        run_write(
            driver,
            """
            MATCH (r:Repo {id: $repo_id})
            MATCH (f:File {uid: $file_uid})
            MERGE (r)-[:CONTAINS]->(f)
            """,
            {"repo_id": repo_id, "file_uid": file_uid},
        )
        return
    folder_uid = f"{repo_id}:{parent}"
    run_write(
        driver,
        """
        MATCH (d:Folder {uid: $folder_uid})
        MATCH (f:File {uid: $file_uid})
        MERGE (d)-[:CONTAINS]->(f)
        """,
        {"folder_uid": folder_uid, "file_uid": file_uid},
    )


def _resolve_module_to_rel_path(module: str) -> str | None:
    if not module:
        return None
    return module.replace(".", "/")


def index_repository(
    driver: Driver,
    repo_id: str,
    root_raw: str,
    *,
    full: bool,
) -> dict:
    root = safe_repo_root(root_raw)
    spec = load_gitignore_spec(root)

    existing = run_read(
        driver,
        "MATCH (r:Repo {id: $id}) RETURN r.name AS name LIMIT 1",
        {"id": repo_id},
    )
    display_name = existing[0]["name"] if existing else repo_id

    if full:
        _delete_repo_graph(driver, repo_id)

    head = ""
    try:
        import git

        r = git.Repo(root, search_parent_directories=False)
        head = r.head.commit.hexsha
    except Exception:
        pass

    now = datetime.now(timezone.utc).isoformat()
    run_write(
        driver,
        """
        MERGE (r:Repo {id: $id})
        SET r.name = $name,
            r.root_path = $root_path,
            r.indexed_at = $indexed_at,
            r.head_commit = $head_commit
        """,
        {
            "id": repo_id,
            "name": display_name,
            "root_path": str(root),
            "indexed_at": now,
            "head_commit": head,
        },
    )

    ensure_constraints(driver)

    files_indexed = 0
    symbols_indexed = 0
    sym_by_qn: dict[tuple[str, str], str] = {}
    imports_pending: list[tuple[str, str, str]] = []  # file_uid, target_rel, module
    indexed_rel_paths: set[str] = set()

    for path, language in iter_indexable_files(root, spec):
        rel = path.relative_to(root).as_posix()
        try:
            content = path.read_bytes()
        except OSError as e:
            logger.warning("Skip unreadable %s: %s", path, e)
            continue
        digest = file_sha256(path)
        file_uid = f"{repo_id}:{rel}"

        if language != "python":
            continue

        indexed_rel_paths.add(rel)
        parsed = parse_python_file(rel, content)

        _ensure_folder_chain(driver, repo_id, rel)

        line_count = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
        run_write(
            driver,
            """
            MERGE (f:File {uid: $uid})
            SET f.repo_id = $repo_id,
                f.path = $path,
                f.hash = $hash,
                f.language = $language,
                f.line_count = $line_count,
                f.name = $name
            """,
            {
                "uid": file_uid,
                "repo_id": repo_id,
                "path": rel,
                "hash": digest,
                "language": language,
                "line_count": line_count,
                "name": path.name,
            },
        )
        _link_file_to_parent_folder(driver, repo_id, file_uid, rel)

        for sym in parsed.symbols:
            sym_uid = f"{repo_id}:{rel}:{sym.qualified_name}:{sym.start_line}"
            sym_by_qn[(rel, sym.qualified_name)] = sym_uid
            run_write(
                driver,
                """
                MATCH (f:File {uid: $file_uid})
                MERGE (s:Symbol {uid: $uid})
                SET s.repo_id = $repo_id,
                    s.file_path = $file_path,
                    s.kind = $kind,
                    s.name = $name,
                    s.qualified_name = $qualified_name,
                    s.start_line = $start_line,
                    s.end_line = $end_line,
                    s.start_col = $start_col,
                    s.end_col = $end_col
                MERGE (f)-[:DEFINES]->(s)
                """,
                {
                    "file_uid": file_uid,
                    "uid": sym_uid,
                    "repo_id": repo_id,
                    "file_path": rel,
                    "kind": sym.kind,
                    "name": sym.name,
                    "qualified_name": sym.qualified_name,
                    "start_line": sym.start_line,
                    "end_line": sym.end_line,
                    "start_col": sym.start_col,
                    "end_col": sym.end_col,
                },
            )
            symbols_indexed += 1

        name_to_syms: dict[str, list[str]] = defaultdict(list)
        for sym in parsed.symbols:
            name_to_syms[sym.name].append(sym_by_qn[(rel, sym.qualified_name)])

        for call in parsed.calls:
            callee = call.callee_hint.split(".")[-1]
            caller_uid = sym_by_qn.get((rel, call.caller_qn))
            if not caller_uid:
                continue
            targets = name_to_syms.get(callee, [])
            for tgt in targets:
                if tgt == caller_uid:
                    continue
                run_write(
                    driver,
                    """
                    MATCH (a:Symbol {uid: $from_uid})
                    MATCH (b:Symbol {uid: $to_uid})
                    MERGE (a)-[c:CALLS]->(b)
                    SET c.repo_id = $repo_id
                    """,
                    {"from_uid": caller_uid, "to_uid": tgt, "repo_id": repo_id},
                )

        for imp in parsed.imports:
            rel_mod = _resolve_module_to_rel_path(imp.module)
            if not rel_mod:
                continue
            candidate = rel_mod + ".py"
            cand_path = root / candidate
            if cand_path.is_file():
                imports_pending.append((file_uid, candidate.replace("\\", "/"), imp.module))
                continue
            init_pkg = root / rel_mod / "__init__.py"
            if init_pkg.is_file():
                pkg_init = str(Path(rel_mod) / "__init__.py")
                imports_pending.append((file_uid, pkg_init.replace("\\", "/"), imp.module))

        files_indexed += 1

    for from_uid, target_rel, module in imports_pending:
        if target_rel not in indexed_rel_paths:
            continue
        to_uid = f"{repo_id}:{target_rel}"
        run_write(
            driver,
            """
            MATCH (a:File {uid: $from_uid})
            MATCH (b:File {uid: $to_uid})
            MERGE (a)-[i:IMPORTS]->(b)
            SET i.repo_id = $repo_id, i.module_hint = $module
            """,
            {"from_uid": from_uid, "to_uid": to_uid, "repo_id": repo_id, "module": module},
        )

    return {
        "repo_id": repo_id,
        "files_indexed": files_indexed,
        "symbols_indexed": symbols_indexed,
        "indexed_at": now,
    }
