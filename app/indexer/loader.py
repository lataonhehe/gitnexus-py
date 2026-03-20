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
        uid = f"folder::{repo_id}::{path}"
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
    folder_uid = f"folder::{repo_id}::{parent}"
    run_write(
        driver,
        """
        MATCH (d:Folder {uid: $folder_uid})
        MATCH (f:File {uid: $file_uid})
        MERGE (d)-[:CONTAINS]->(f)
        """,
        {"folder_uid": folder_uid, "file_uid": file_uid},
    )


def _symbol_uid(repo_id: str, rel: str, sym) -> str:
    if sym.kind == "class":
        return f"class::{repo_id}::{rel}::{sym.qualified_name}"
    if sym.kind == "method":
        return f"method::{repo_id}::{rel}::{sym.qualified_name}"
    return f"func::{repo_id}::{rel}::{sym.qualified_name}"


def _merge_symbol_node(
    driver: Driver,
    repo_id: str,
    file_uid: str,
    rel: str,
    sym,
    uid: str,
) -> None:
    label = "Class" if sym.kind == "class" else ("Method" if sym.kind == "method" else "Function")
    run_write(
        driver,
        f"""
        MATCH (f:File {{uid: $file_uid}})
        MERGE (s:{label} {{uid: $uid}})
        SET s.repo_id = $repo_id,
            s.file_path = $file_path,
            s.name = $name,
            s.signature = $signature,
            s.docstring = $docstring,
            s.start_line = $start_line,
            s.end_line = $end_line
        MERGE (f)-[:DEFINES]->(s)
        """,
        {
            "file_uid": file_uid,
            "uid": uid,
            "repo_id": repo_id,
            "file_path": rel,
            "name": sym.name,
            "signature": sym.signature or "",
            "docstring": sym.docstring or "",
            "start_line": sym.start_line,
            "end_line": sym.end_line,
        },
    )


def _link_method_to_class(
    driver: Driver,
    rel: str,
    sym,
    method_uid: str,
    sym_by_qn: dict,
) -> None:
    if sym.kind != "method":
        return
    parts = sym.qualified_name.split(".")
    if len(parts) < 2:
        return
    parent_qn = ".".join(parts[:-1])
    class_uid = sym_by_qn.get((rel, parent_qn))
    if not class_uid:
        return
    run_write(
        driver,
        """
        MATCH (c:Class {uid: $class_uid})
        MATCH (m:Method {uid: $method_uid})
        MERGE (c)-[:HAS_METHOD]->(m)
        """,
        {"class_uid": class_uid, "method_uid": method_uid},
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
            r.head_commit = $head_commit,
            r.status = $status
        """,
        {
            "id": repo_id,
            "name": display_name,
            "root_path": str(root),
            "indexed_at": now,
            "head_commit": head,
            "status": "indexing",
        },
    )

    ensure_constraints(driver)

    files_indexed = 0
    symbols_indexed = 0
    edges_written = 0
    sym_by_qn: dict[tuple[str, str], str] = {}
    imports_pending: list[tuple[str, str, str]] = []
    indexed_rel_paths: set[str] = set()

    for path, language in iter_indexable_files(root, spec):
        rel = path.relative_to(root).as_posix()
        try:
            content = path.read_bytes()
        except OSError as e:
            logger.warning("Skip unreadable %s: %s", path, e)
            continue
        digest = file_sha256(path)
        file_uid = f"file::{repo_id}::{rel}"

        if language != "python":
            continue

        if not full:
            prev = run_read(
                driver,
                "MATCH (f:File {uid: $uid}) RETURN f.content_hash AS h LIMIT 1",
                {"uid": file_uid},
            )
            if prev and prev[0].get("h") == digest:
                indexed_rel_paths.add(rel)
                files_indexed += 1
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
                f.content_hash = $content_hash,
                f.hash = $content_hash,
                f.language = $language,
                f.line_count = $line_count,
                f.name = $name
            """,
            {
                "uid": file_uid,
                "repo_id": repo_id,
                "path": rel,
                "content_hash": digest,
                "language": language,
                "line_count": line_count,
                "name": path.name,
            },
        )
        _link_file_to_parent_folder(driver, repo_id, file_uid, rel)

        for sym in parsed.symbols:
            uid = _symbol_uid(repo_id, rel, sym)
            sym_by_qn[(rel, sym.qualified_name)] = uid
            _merge_symbol_node(driver, repo_id, file_uid, rel, sym, uid)
            _link_method_to_class(driver, rel, sym, uid, sym_by_qn)
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
                conf = 1.0
                run_write(
                    driver,
                    """
                    MATCH (a {uid: $from_uid})
                    MATCH (b {uid: $to_uid})
                    WHERE (a:Function OR a:Method) AND (b:Function OR b:Method)
                    MERGE (a)-[c:CALLS]->(b)
                    SET c.repo_id = $repo_id, c.confidence = $confidence
                    """,
                    {
                        "from_uid": caller_uid,
                        "to_uid": tgt,
                        "repo_id": repo_id,
                        "confidence": conf,
                    },
                )
                edges_written += 1

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
        to_uid = f"file::{repo_id}::{target_rel}"
        run_write(
            driver,
            """
            MATCH (a:File {uid: $from_uid})
            MATCH (b:File {uid: $to_uid})
            MERGE (a)-[i:IMPORTS]->(b)
            SET i.repo_id = $repo_id, i.module_hint = $module, i.confidence = 0.9
            """,
            {"from_uid": from_uid, "to_uid": to_uid, "repo_id": repo_id, "module": module},
        )
        edges_written += 1

    fc_rows = run_read(
        driver,
        "MATCH (f:File {repo_id: $rid}) RETURN count(f) AS c",
        {"rid": repo_id},
    )
    sc_rows = run_read(
        driver,
        """
        MATCH (s)
        WHERE s.repo_id = $rid AND (s:Function OR s:Class OR s:Method)
        RETURN count(s) AS c
        """,
        {"rid": repo_id},
    )
    file_count_total = int(fc_rows[0]["c"]) if fc_rows else 0
    symbol_count_total = int(sc_rows[0]["c"]) if sc_rows else 0

    edge_rows = run_read(
        driver,
        """
        MATCH (a {repo_id: $rid})-[r]->(b {repo_id: $rid})
        RETURN count(r) AS c
        """,
        {"rid": repo_id},
    )
    edge_count = int(edge_rows[0]["c"]) if edge_rows else 0

    run_write(
        driver,
        """
        MATCH (r:Repo {id: $id})
        SET r.status = $status,
            r.file_count = $file_count,
            r.symbol_count = $symbol_count,
            r.edge_count = $edge_count,
            r.indexed_at = $indexed_at,
            r.head_commit = $head_commit
        """,
        {
            "id": repo_id,
            "status": "ready",
            "file_count": file_count_total,
            "symbol_count": symbol_count_total,
            "edge_count": edge_count,
            "indexed_at": now,
            "head_commit": head,
        },
    )

    return {
        "repo_id": repo_id,
        "files_indexed": file_count_total,
        "symbols_indexed": symbol_count_total,
        "files_processed_this_run": files_indexed,
        "symbols_upserted_this_run": symbols_indexed,
        "edges_indexed": edges_written,
        "edge_count": edge_count,
        "indexed_at": now,
    }
