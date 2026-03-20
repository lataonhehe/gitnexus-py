from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from neo4j import READ_ACCESS, WRITE_ACCESS, Driver, GraphDatabase

from app.config import get_settings

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def get_driver(settings: Settings | None = None) -> Driver | None:
    global _driver
    s = settings or get_settings()
    if not s.neo4j_enabled or not s.neo4j_uri:
        return None
    if _driver is None:
        _driver = GraphDatabase.driver(
            s.neo4j_uri,
            auth=(s.neo4j_user, s.neo4j_password),
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


def _session_kwargs(settings: Settings) -> dict[str, Any]:
    db = (settings.neo4j_database or "").strip()
    if db:
        return {"database": db}
    return {}


@contextmanager
def read_session(driver: Driver, settings: Settings | None = None) -> Iterator[Any]:
    s = settings or get_settings()
    with driver.session(default_access_mode=READ_ACCESS, **_session_kwargs(s)) as session:
        yield session


@contextmanager
def write_session(driver: Driver, settings: Settings | None = None) -> Iterator[Any]:
    s = settings or get_settings()
    with driver.session(default_access_mode=WRITE_ACCESS, **_session_kwargs(s)) as session:
        yield session


def run_read(
    driver: Driver,
    query: str,
    parameters: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    parameters = parameters or {}
    with read_session(driver, settings) as session:
        result = session.run(query, parameters)
        return [dict(r) for r in result]


def run_write(
    driver: Driver,
    query: str,
    parameters: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
) -> None:
    parameters = parameters or {}
    with write_session(driver, settings) as session:
        session.run(query, parameters)


def run_write_returning(
    driver: Driver,
    query: str,
    parameters: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Write transaction (MERGE/SET/CREATE/…) that also RETURNs rows."""
    parameters = parameters or {}
    with write_session(driver, settings) as session:
        result = session.run(query, parameters)
        return [dict(r) for r in result]


def ensure_constraints(driver: Driver, settings: Settings | None = None) -> None:
    stmts = [
        "CREATE CONSTRAINT repo_id_unique IF NOT EXISTS FOR (r:Repo) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT file_uid_unique IF NOT EXISTS FOR (f:File) REQUIRE f.uid IS UNIQUE",
        (
            "CREATE CONSTRAINT function_uid_unique IF NOT EXISTS "
            "FOR (fn:Function) REQUIRE fn.uid IS UNIQUE"
        ),
        "CREATE CONSTRAINT class_uid_unique IF NOT EXISTS FOR (c:Class) REQUIRE c.uid IS UNIQUE",
        "CREATE CONSTRAINT method_uid_unique IF NOT EXISTS FOR (m:Method) REQUIRE m.uid IS UNIQUE",
        "CREATE INDEX file_path IF NOT EXISTS FOR (f:File) ON (f.path)",
        "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
        "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
        "CREATE INDEX method_name IF NOT EXISTS FOR (m:Method) ON (m.name)",
    ]
    for q in stmts:
        try:
            run_write(driver, q, settings=settings)
        except Exception as e:
            logger.debug("Schema stmt may already exist: %s — %s", q, e)
