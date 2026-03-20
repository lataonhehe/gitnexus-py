from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from neo4j import READ_ACCESS, Driver, GraphDatabase

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def get_driver(settings: Settings) -> Driver | None:
    global _driver
    if not settings.neo4j_enabled or not settings.neo4j_uri:
        return None
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def verify_connectivity(driver: Driver) -> bool:
    try:
        driver.verify_connectivity()
        return True
    except Exception as e:
        logger.warning("Neo4j connectivity check failed: %s", e)
        return False


def run_read(
    driver: Driver,
    query: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    parameters = parameters or {}
    with driver.session(default_access_mode=READ_ACCESS) as session:
        result = session.run(query, parameters)
        return [dict(r) for r in result]


def run_write(driver: Driver, query: str, parameters: dict[str, Any] | None = None) -> None:
    parameters = parameters or {}
    with driver.session() as session:
        session.run(query, parameters)


def run_write_returning(
    driver: Driver,
    query: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Write transaction (MERGE/SET/CREATE/…) that also RETURNs rows."""
    parameters = parameters or {}
    with driver.session() as session:
        result = session.run(query, parameters)
        return [dict(r) for r in result]


def ensure_constraints(driver: Driver) -> None:
    stmts = [
        "CREATE CONSTRAINT repo_id_unique IF NOT EXISTS FOR (r:Repo) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT file_uid_unique IF NOT EXISTS FOR (f:File) REQUIRE f.uid IS UNIQUE",
        "CREATE CONSTRAINT symbol_uid_unique IF NOT EXISTS FOR (s:Symbol) REQUIRE s.uid IS UNIQUE",
    ]
    for q in stmts:
        try:
            run_write(driver, q)
        except Exception as e:
            logger.debug("Constraint may already exist: %s — %s", q, e)
