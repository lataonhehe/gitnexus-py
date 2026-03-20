from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import settings_dep
from app.config import Settings
from app.db.neo4j_client import get_driver, verify_connectivity

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(settings: Annotated[Settings, Depends(settings_dep)]):
    if not settings.neo4j_enabled:
        return {"status": "ready", "neo4j": "skipped"}
    driver = get_driver(settings)
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "neo4j": "not_configured"},
        )
    if verify_connectivity(driver):
        return {"status": "ready", "neo4j": "connected"}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"status": "not_ready", "neo4j": "unreachable"},
    )
