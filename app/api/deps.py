from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings
from app.db.neo4j_client import get_driver, verify_connectivity


def settings_dep() -> Settings:
    return get_settings()


def neo4j_driver_dep(settings: Annotated[Settings, Depends(settings_dep)]):
    driver = get_driver(settings)
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j is not configured (set GITNEXUS_NEO4J_URI or enable graph).",
        )
    return driver


def require_neo4j_ready(settings: Annotated[Settings, Depends(settings_dep)]):
    if not settings.neo4j_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j disabled.",
        )
    driver = get_driver(settings)
    if driver is None or not verify_connectivity(driver):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j unreachable.",
        )
    return driver
