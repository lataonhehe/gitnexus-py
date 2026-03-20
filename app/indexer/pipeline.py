from __future__ import annotations

from neo4j import Driver

from app.indexer.loader import index_repository


def run_index(driver: Driver, repo_id: str, root_path: str, *, force: bool = True) -> dict:
    """Orchestrate full indexing for a registered repo (plan phase 2g)."""
    return index_repository(driver, repo_id, root_path, full=force)
