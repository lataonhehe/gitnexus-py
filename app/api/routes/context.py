from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from neo4j.graph import Node

from app.api.deps import neo4j_driver_dep
from app.db.neo4j_client import run_read
from app.models.api import ContextMatch, ContextRequest, ContextResponse
from app.services.neo4j_json import simplify_value

router = APIRouter(tags=["context"])


def _sym_row(r: dict[str, Any]) -> ContextMatch:
    s = r.get("s") or r
    if isinstance(s, Node):
        d = dict(s)
    elif isinstance(s, dict):
        d = s
    else:
        d = {k: s[k] for k in s.keys()}
    return ContextMatch(
        uid=d.get("uid", ""),
        name=d.get("name", ""),
        kind=d.get("kind", ""),
        file_path=d.get("file_path", ""),
        qualified_name=d.get("qualified_name"),
    )


@router.post("/context", response_model=ContextResponse)
def context(req: ContextRequest, driver=Depends(neo4j_driver_dep)):
    rid = req.repo_id
    matches: list[dict[str, Any]] = []

    if req.uid:
        matches = run_read(
            driver,
            """
            MATCH (s:Symbol {repo_id: $rid, uid: $uid})
            RETURN s
            LIMIT 25
            """,
            {"rid": rid, "uid": req.uid},
        )
    elif req.name and req.file_path:
        matches = run_read(
            driver,
            """
            MATCH (s:Symbol {repo_id: $rid, name: $name, file_path: $fp})
            RETURN s
            LIMIT 25
            """,
            {"rid": rid, "name": req.name, "fp": req.file_path},
        )
    elif req.name:
        matches = run_read(
            driver,
            """
            MATCH (s:Symbol {repo_id: $rid, name: $name})
            RETURN s
            LIMIT 25
            """,
            {"rid": rid, "name": req.name},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide uid or name (optionally with file_path).",
        )

    if not matches:
        return ContextResponse(disambiguation=[], selected=None)

    dis = [_sym_row(m) for m in matches]
    if len(matches) > 1 and not req.uid:
        return ContextResponse(disambiguation=dis, selected=None)

    sel = dis[0]
    uid = sel.uid

    callees = run_read(
        driver,
        """
        MATCH (s:Symbol {uid: $uid})-[:CALLS]->(t:Symbol)
        RETURN t.uid AS uid, t.name AS name, t.kind AS kind, t.file_path AS file_path,
               t.qualified_name AS qualified_name
        LIMIT 80
        """,
        {"uid": uid},
    )
    callers = run_read(
        driver,
        """
        MATCH (t:Symbol)-[:CALLS]->(s:Symbol {uid: $uid})
        RETURN t.uid AS uid, t.name AS name, t.kind AS kind, t.file_path AS file_path,
               t.qualified_name AS qualified_name
        LIMIT 80
        """,
        {"uid": uid},
    )
    imports = run_read(
        driver,
        """
        MATCH (s:Symbol {uid: $uid})<-[:DEFINES]-(f:File)-[:IMPORTS]->(t:File)
        RETURN DISTINCT t.path AS path, t.uid AS uid
        LIMIT 80
        """,
        {"uid": uid},
    )
    imported_by = run_read(
        driver,
        """
        MATCH (s:Symbol {uid: $uid})<-[:DEFINES]-(f:File)<-[:IMPORTS]-(x:File)
        RETURN DISTINCT x.path AS path, x.uid AS uid
        LIMIT 80
        """,
        {"uid": uid},
    )

    return ContextResponse(
        disambiguation=dis,
        selected=sel,
        callers=[{k: simplify_value(v) for k, v in r.items()} for r in callers],
        callees=[{k: simplify_value(v) for k, v in r.items()} for r in callees],
        imports=[{k: simplify_value(v) for k, v in r.items()} for r in imports],
        imported_by=[{k: simplify_value(v) for k, v in r.items()} for r in imported_by],
    )
