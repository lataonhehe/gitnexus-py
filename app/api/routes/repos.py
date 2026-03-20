from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import neo4j_driver_dep
from app.db.neo4j_client import run_read, run_write_returning
from app.indexer.loader import index_repository
from app.indexer.paths import safe_repo_root
from app.models.api import IndexRequest, RepoCreate, RepoOut
from app.services.repo_schema import GRAPH_SCHEMA

router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("", response_model=RepoOut)
def register_repo(
    body: RepoCreate,
    driver=Depends(neo4j_driver_dep),
):
    try:
        root = safe_repo_root(body.root_path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    rows = run_write_returning(
        driver,
        """
        MERGE (r:Repo {id: $id})
        SET r.name = $name, r.root_path = $root_path
        RETURN r.id AS id, r.name AS name, r.root_path AS root_path,
               r.indexed_at AS indexed_at, r.head_commit AS head_commit
        """,
        {"id": body.id, "name": body.name, "root_path": str(root)},
    )
    r = rows[0]
    return RepoOut(
        id=r["id"],
        name=r["name"],
        root_path=r["root_path"],
        indexed_at=r.get("indexed_at"),
        head_commit=r.get("head_commit"),
    )


@router.get("", response_model=list[RepoOut])
def list_repos(driver=Depends(neo4j_driver_dep)):
    rows = run_read(
        driver,
        """
        MATCH (r:Repo)
        RETURN r.id AS id, r.name AS name, r.root_path AS root_path,
               r.indexed_at AS indexed_at, r.head_commit AS head_commit
        ORDER BY r.id
        """,
    )
    return [
        RepoOut(
            id=x["id"],
            name=x["name"],
            root_path=x["root_path"],
            indexed_at=x.get("indexed_at"),
            head_commit=x.get("head_commit"),
        )
        for x in rows
    ]


@router.post("/{repo_id}/index")
def run_index(
    repo_id: str,
    body: IndexRequest,
    driver=Depends(neo4j_driver_dep),
):
    rows = run_read(
        driver,
        "MATCH (r:Repo {id: $id}) RETURN r.root_path AS root_path LIMIT 1",
        {"id": repo_id},
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found.")
    root_path = rows[0]["root_path"]
    stats = index_repository(driver, repo_id, root_path, full=body.full)
    return stats


@router.get("/{repo_id}/schema")
def repo_schema(repo_id: str, driver=Depends(neo4j_driver_dep)):
    rows = run_read(
        driver,
        "MATCH (r:Repo {id: $id}) RETURN r.id AS id LIMIT 1",
        {"id": repo_id},
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found.")
    return {"repo_id": repo_id, "graph": GRAPH_SCHEMA}
