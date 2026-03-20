from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import settings_dep
from app.config import Settings
from app.db.neo4j_client import get_driver, verify_connectivity

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Annotated[Settings, Depends(settings_dep)]):
    return {"status": "ok", "app": settings.app_name}


@router.get("/ready")
def ready(settings: Annotated[Settings, Depends(settings_dep)]):
    if not settings.neo4j_enabled:
        return {"status": "ready", "neo4j": "skipped"}
    driver = get_driver(settings)
    if driver is None:
        return {"status": "not_ready", "neo4j": "not_configured"}
    ok = verify_connectivity(driver)
    if ok:
        return {"status": "ready", "neo4j": "ok"}
    return {"status": "not_ready", "neo4j": "unreachable"}
