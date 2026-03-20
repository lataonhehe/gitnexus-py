"""Neo4j-backed repo registry helpers (plan phase 2b)."""

from __future__ import annotations

from neo4j import Driver

from app.db.neo4j_client import run_read, run_write


def set_repo_status(driver: Driver, repo_id: str, status: str) -> None:
    run_write(
        driver,
        """
        MATCH (r:Repo {id: $id})
        SET r.status = $status
        """,
        {"id": repo_id, "status": status},
    )


def get_repo_row(driver: Driver, repo_id: str) -> dict | None:
    rows = run_read(
        driver,
        """
        MATCH (r:Repo {id: $id})
        RETURN r.id AS id, r.name AS name, r.root_path AS root_path,
               r.git_url AS git_url, r.git_branch AS git_branch,
               r.indexed_at AS indexed_at, r.head_commit AS head_commit,
               r.status AS status, r.file_count AS file_count,
               r.symbol_count AS symbol_count, r.edge_count AS edge_count
        LIMIT 1
        """,
        {"id": repo_id},
    )
    return rows[0] if rows else None
