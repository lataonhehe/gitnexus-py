from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from neo4j import READ_ACCESS

from app.api.deps import neo4j_driver_dep, settings_dep
from app.config import Settings
from app.core.errors import GitNexusError
from app.db.neo4j_client import run_read, run_write, run_write_returning
from app.indexer.loader import index_repository
from app.indexer.paths import safe_repo_root
from app.models.api import (
    ContextRefV3,
    ContextRequestV3,
    ContextResponseV3,
    ContextSymbolV3,
    CypherRequest,
    CypherResponseV3,
    DefinedInV3,
    IndexRequest,
    RepoCreate,
    RepoListItem,
    RepoListResponse,
    RepoOut,
    RepoStats,
    slug_from_name,
)
from app.services.cypher_guard import validate_cypher
from app.services.git_clone import (
    clone_destination,
    git_pull_ff,
    prepare_git_worktree,
    validate_git_url_for_clone,
)
from app.services.neo4j_json import json_cell
from app.services.repo_schema import SCHEMA_RESOURCE

router = APIRouter(prefix="/repos", tags=["repos"])

_REPO_ROW_RETURN = """
        r.id AS id, r.name AS name, r.root_path AS root_path,
        r.git_url AS git_url, r.git_branch AS git_branch,
        r.indexed_at AS indexed_at, r.head_commit AS head_commit, r.status AS status,
        coalesce(r.file_count, 0) AS file_count,
        coalesce(r.symbol_count, 0) AS symbol_count,
        coalesce(r.edge_count, 0) AS edge_count
"""


def _remove_managed_clone(root_path: str, settings: Settings) -> None:
    try:
        p = Path(root_path).resolve()
        base = (settings.data_dir.expanduser().resolve() / "clones").resolve()
        if p.parent == base or base in p.parents:
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _repo_row_for_index(driver, repo_id: str) -> dict[str, Any]:
    rows = run_read(
        driver,
        """
        MATCH (r:Repo {id: $id})
        RETURN r.root_path AS root_path, r.git_url AS git_url, r.git_branch AS git_branch
        LIMIT 1
        """,
        {"id": repo_id},
    )
    if not rows:
        raise GitNexusError("REPO_NOT_FOUND", f"Repo '{repo_id}' not found", 404)
    return rows[0]


def _maybe_git_pull(row: dict[str, Any], pull: bool, settings: Settings) -> None:
    if not pull or not row.get("git_url"):
        return
    root = Path(row["root_path"])
    try:
        git_pull_ff(root, settings)
    except RuntimeError as e:
        raise GitNexusError("GIT_PULL_FAILED", str(e), 502) from e


def _require_repo(driver, repo_id: str) -> None:
    rows = run_read(
        driver,
        "MATCH (r:Repo {id: $id}) RETURN r.id AS id LIMIT 1",
        {"id": repo_id},
    )
    if not rows:
        raise GitNexusError("REPO_NOT_FOUND", f"Repo '{repo_id}' not found", 404)


def _row_to_repo_out(r: dict) -> RepoOut:
    stats = RepoStats(
        file_count=int(r.get("file_count") or 0),
        symbol_count=int(r.get("symbol_count") or 0),
        edge_count=int(r.get("edge_count") or 0),
    )
    return RepoOut(
        id=r["id"],
        name=r["name"],
        root_path=r["root_path"],
        git_url=r.get("git_url"),
        git_branch=r.get("git_branch"),
        status=r.get("status"),
        indexed_at=r.get("indexed_at"),
        head_commit=r.get("head_commit"),
        stats=stats,
    )


def _row_to_list_item(r: dict) -> RepoListItem:
    st = RepoStats(
        file_count=int(r.get("file_count") or 0),
        symbol_count=int(r.get("symbol_count") or 0),
        edge_count=int(r.get("edge_count") or 0),
    )
    return RepoListItem(
        id=r["id"],
        name=r["name"],
        root_path=r["root_path"],
        git_url=r.get("git_url"),
        git_branch=r.get("git_branch"),
        status=r.get("status"),
        indexed_at=r.get("indexed_at"),
        head_commit=r.get("head_commit"),
        stats=st,
    )


@router.post("", response_model=RepoOut)
def register_repo(
    body: RepoCreate,
    settings: Annotated[Settings, Depends(settings_dep)],
    driver=Depends(neo4j_driver_dep),
):
    rid = body.id or slug_from_name(body.name)
    branch = (body.branch or "").strip() or None
    git_url_norm: str | None = None
    if body.git_url:
        try:
            git_url_norm = validate_git_url_for_clone(body.git_url, settings)
        except ValueError as e:
            raise GitNexusError("INVALID_GIT_URL", str(e), 400) from e
        dest = clone_destination(rid, settings)
        try:
            prepare_git_worktree(
                git_url_norm,
                dest,
                branch=branch,
                settings=settings,
                force_fresh_clone=body.force_clone,
            )
        except RuntimeError as e:
            raise GitNexusError("GIT_CLONE_FAILED", str(e), 502) from e
        root = str(dest.resolve())
    else:
        try:
            root = str(safe_repo_root(body.path or ""))
        except ValueError as e:
            raise GitNexusError("INVALID_PATH", str(e), 400) from e
        git_url_norm = None
        branch = None

    rows = run_write_returning(
        driver,
        f"""
        MERGE (r:Repo {{id: $id}})
        SET r.name = $name,
            r.root_path = $root_path,
            r.git_url = $git_url,
            r.git_branch = $git_branch,
            r.status = coalesce(r.status, 'registered')
        RETURN {_REPO_ROW_RETURN.strip()}
        """,
        {
            "id": rid,
            "name": body.name,
            "root_path": root,
            "git_url": git_url_norm,
            "git_branch": branch,
        },
    )
    r = rows[0]
    if body.trigger_index:
        index_repository(driver, rid, str(root), full=True)
        rows2 = run_read(
            driver,
            f"""
            MATCH (r:Repo {{id: $id}})
            RETURN {_REPO_ROW_RETURN.strip()}
            LIMIT 1
            """,
            {"id": rid},
        )
        if rows2:
            r = rows2[0]
    return _row_to_repo_out(r)


@router.get("", response_model=RepoListResponse)
def list_repos(driver=Depends(neo4j_driver_dep)):
    rows = run_read(
        driver,
        f"""
        MATCH (r:Repo)
        RETURN {_REPO_ROW_RETURN.strip()}
        ORDER BY r.id
        """,
    )
    return RepoListResponse(repos=[_row_to_list_item(x) for x in rows])


@router.get("/{repo_id}", response_model=RepoOut)
def get_repo(repo_id: str, driver=Depends(neo4j_driver_dep)):
    rows = run_read(
        driver,
        f"""
        MATCH (r:Repo {{id: $id}})
        RETURN {_REPO_ROW_RETURN.strip()}
        LIMIT 1
        """,
        {"id": repo_id},
    )
    if not rows:
        raise GitNexusError("REPO_NOT_FOUND", f"Repo '{repo_id}' not found", 404)
    return _row_to_repo_out(rows[0])


@router.delete("/{repo_id}")
def delete_repo(
    repo_id: str,
    settings: Annotated[Settings, Depends(settings_dep)],
    driver=Depends(neo4j_driver_dep),
):
    rows = run_read(
        driver,
        "MATCH (r:Repo {id: $id}) RETURN r.id AS id, r.root_path AS root_path LIMIT 1",
        {"id": repo_id},
    )
    if not rows:
        raise GitNexusError("REPO_NOT_FOUND", f"Repo '{repo_id}' not found", 404)
    root_path = rows[0].get("root_path")
    run_write(driver, "MATCH (n {repo_id: $id}) DETACH DELETE n", {"id": repo_id})
    run_write(driver, "MATCH (r:Repo {id: $id}) DETACH DELETE r", {"id": repo_id})
    if root_path:
        _remove_managed_clone(str(root_path), settings)
    return {"deleted": True, "id": repo_id}


@router.post("/{repo_id}/index")
def run_index(
    repo_id: str,
    body: IndexRequest,
    settings: Annotated[Settings, Depends(settings_dep)],
    driver=Depends(neo4j_driver_dep),
):
    row = _repo_row_for_index(driver, repo_id)
    _maybe_git_pull(row, body.pull, settings)
    return index_repository(driver, repo_id, row["root_path"], full=body.full)


@router.post("/{repo_id}/reindex")
def reindex(
    repo_id: str,
    settings: Annotated[Settings, Depends(settings_dep)],
    driver=Depends(neo4j_driver_dep),
    pull: bool = Query(
        True,
        description="If repo has git_url, run git pull --ff-only before full reindex",
    ),
):
    row = _repo_row_for_index(driver, repo_id)
    _maybe_git_pull(row, pull, settings)
    return index_repository(driver, repo_id, row["root_path"], full=True)


@router.get("/{repo_id}/schema")
def repo_schema(repo_id: str, driver=Depends(neo4j_driver_dep)):
    _require_repo(driver, repo_id)
    return SCHEMA_RESOURCE


def _execute_cypher(
    driver,
    settings: Settings,
    query: str,
    parameters: dict[str, Any],
    max_rows: int,
):
    kwargs: dict[str, Any] = {}
    db = (settings.neo4j_database or "").strip()
    if db:
        kwargs["database"] = db
    fetch_limit = max_rows + 1
    with driver.session(default_access_mode=READ_ACCESS, **kwargs) as session:
        result = session.run(query, parameters)
        keys = list(result.keys())
        out_rows: list[dict[str, Any]] = []
        for i, record in enumerate(result):
            if i >= fetch_limit:
                break
            out_rows.append({k: json_cell(record[k]) for k in keys})
        truncated = len(out_rows) > max_rows
        if truncated:
            out_rows = out_rows[:max_rows]
        return keys, out_rows, truncated


@router.post("/{repo_id}/cypher", response_model=CypherResponseV3)
def run_repo_cypher(
    repo_id: str,
    req: CypherRequest,
    settings: Annotated[Settings, Depends(settings_dep)],
    driver=Depends(neo4j_driver_dep),
):
    _require_repo(driver, repo_id)
    ok, err = validate_cypher(req.query, read_only=settings.cypher_read_only)
    if not ok:
        raise GitNexusError("CYPHER_FORBIDDEN", err or "Query not allowed", 403)
    timeout = settings.cypher_timeout_seconds
    max_rows = settings.cypher_max_rows
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(
                _execute_cypher,
                driver,
                settings,
                req.query,
                req.parameters,
                max_rows,
            )
            cols, rows, truncated = fut.result(timeout=timeout)
    except FuturesTimeout:
        raise GitNexusError(
            "CYPHER_TIMEOUT",
            f"Cypher exceeded timeout of {timeout}s.",
            504,
        ) from None
    except GitNexusError:
        raise
    except Exception as e:
        raise GitNexusError("CYPHER_ERROR", str(e), 400) from e
    return CypherResponseV3(
        columns=cols,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )


def _symbol_primary_label(labels: list[str]) -> str:
    for lab in ("Function", "Method", "Class"):
        if lab in labels:
            return lab
    return labels[0] if labels else "CodeElement"


@router.post("/{repo_id}/context", response_model=ContextResponseV3)
def repo_context(
    repo_id: str,
    req: ContextRequestV3,
    driver=Depends(neo4j_driver_dep),
):
    _require_repo(driver, repo_id)
    rid = repo_id
    depth = req.depth
    matches: list[dict[str, Any]] = []

    if req.uid:
        matches = run_read(
            driver,
            """
            MATCH (s)
            WHERE s.repo_id = $rid AND s.uid = $uid
              AND (s:Function OR s:Class OR s:Method)
            RETURN s AS s, labels(s) AS labels
            LIMIT 25
            """,
            {"rid": rid, "uid": req.uid},
        )
    elif req.name and req.file_path:
        matches = run_read(
            driver,
            """
            MATCH (s)
            WHERE s.repo_id = $rid AND s.name = $name AND s.file_path = $fp
              AND (s:Function OR s:Class OR s:Method)
            RETURN s AS s, labels(s) AS labels
            LIMIT 25
            """,
            {"rid": rid, "name": req.name, "fp": req.file_path},
        )
    elif req.name:
        matches = run_read(
            driver,
            """
            MATCH (s)
            WHERE s.repo_id = $rid AND s.name = $name
              AND (s:Function OR s:Class OR s:Method)
            RETURN s AS s, labels(s) AS labels
            LIMIT 25
            """,
            {"rid": rid, "name": req.name},
        )

    def to_ref(row: dict, labels: list[str]) -> ContextRefV3:
        s = row["s"]
        d = dict(s)
        return ContextRefV3(
            uid=d.get("uid", ""),
            name=d.get("name", ""),
            file_path=d.get("file_path", ""),
            label=_symbol_primary_label(labels),
        )

    def disambiguation_response(rows: list[dict[str, Any]], hint: str) -> ContextResponseV3:
        refs: list[ContextRefV3] = []
        for m in rows:
            labels = list(m.get("labels") or ())
            refs.append(to_ref(m, labels))
        return ContextResponseV3(
            symbol=None,
            callers=[],
            callees=[],
            defined_in=None,
            disambiguation=refs,
            hint=hint,
        )

    if not matches:
        raise GitNexusError(
            "SYMBOL_NOT_FOUND",
            f"No symbol named '{req.name or req.uid}'",
            404,
        )

    picked: list[dict[str, Any]]
    if req.uid or len(matches) == 1:
        picked = matches[:1]
    elif req.file_path:
        filt = [m for m in matches if dict(m["s"]).get("file_path") == req.file_path]
        if len(filt) == 1:
            picked = filt
        elif len(filt) > 1:
            return disambiguation_response(
                filt,
                f"Multiple symbols named '{req.name}' in '{req.file_path}'. Retry with uid.",
            )
        else:
            return disambiguation_response(
                matches,
                (
                    f"No symbol named '{req.name}' in '{req.file_path}'. "
                    "See candidates or retry with uid."
                ),
            )
    else:
        return disambiguation_response(
            matches,
            f"Multiple symbols named '{req.name}'. Retry with uid or file_path to disambiguate.",
        )

    m0 = picked[0]
    labels = m0.get("labels") or []
    if isinstance(labels, tuple):
        labels = list(labels)
    snode = dict(m0["s"])
    uid = snode.get("uid", "")
    plab = _symbol_primary_label(labels)

    sym = ContextSymbolV3(
        uid=uid,
        name=snode.get("name", ""),
        label=plab,
        signature=snode.get("signature") or "",
        docstring=snode.get("docstring") or "",
        file_path=snode.get("file_path", ""),
        start_line=int(snode.get("start_line") or 0),
        end_line=int(snode.get("end_line") or 0),
    )

    range_lit = f"*1..{depth}"
    callers_raw = run_read(
        driver,
        f"""
        MATCH (caller)-[:CALLS{range_lit}]->(target {{uid: $uid}})
        WHERE target.repo_id = $rid
          AND (caller:Function OR caller:Method)
        WITH DISTINCT caller
        RETURN caller AS s, labels(caller) AS labels
        LIMIT 20
        """,
        {"uid": uid, "rid": rid},
    )
    callees_raw = run_read(
        driver,
        f"""
        MATCH (target {{uid: $uid}})-[:CALLS{range_lit}]->(callee)
        WHERE target.repo_id = $rid
          AND (callee:Function OR callee:Method)
        WITH DISTINCT callee
        RETURN callee AS s, labels(callee) AS labels
        LIMIT 20
        """,
        {"uid": uid, "rid": rid},
    )

    callers = []
    for r in callers_raw:
        lab = r.get("labels") or []
        if isinstance(lab, tuple):
            lab = list(lab)
        callers.append(to_ref(r, lab))

    callees = []
    for r in callees_raw:
        lab = r.get("labels") or []
        if isinstance(lab, tuple):
            lab = list(lab)
        callees.append(to_ref(r, lab))

    fin = run_read(
        driver,
        """
        MATCH (f:File)-[:DEFINES]->(s {uid: $uid})
        RETURN f.uid AS uid, f.path AS path
        LIMIT 1
        """,
        {"uid": uid},
    )
    defined = None
    if fin:
        defined = DefinedInV3(uid=fin[0].get("uid", ""), path=fin[0].get("path", ""))

    return ContextResponseV3(
        symbol=sym,
        callers=callers,
        callees=callees,
        defined_in=defined,
        disambiguation=[],
        hint=None,
    )
