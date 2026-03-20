from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from neo4j import READ_ACCESS

from app.api.deps import neo4j_driver_dep, settings_dep
from app.config import Settings
from app.models.api import CypherRequest, CypherResponse
from app.services.cypher_guard import validate_cypher
from app.services.neo4j_json import simplify_value

router = APIRouter(tags=["cypher"])


def _execute_cypher(driver, query: str, parameters: dict[str, Any], max_rows: int):
    with driver.session(default_access_mode=READ_ACCESS) as session:
        result = session.run(query, parameters)
        keys = list(result.keys())
        rows: list[list[Any]] = []
        truncated = False
        for i, record in enumerate(result):
            if i >= max_rows:
                truncated = True
                break
            rows.append([simplify_value(record[k]) for k in keys])
        return keys, rows, truncated


@router.post("/cypher", response_model=CypherResponse)
def run_cypher(
    req: CypherRequest,
    settings: Annotated[Settings, Depends(settings_dep)],
    driver=Depends(neo4j_driver_dep),
):
    ok, err = validate_cypher(req.query, read_only=settings.cypher_read_only)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    timeout = settings.cypher_timeout_seconds
    max_rows = settings.cypher_max_rows
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(
                _execute_cypher,
                driver,
                req.query,
                req.parameters,
                max_rows,
            )
            cols, rows, truncated = fut.result(timeout=timeout)
    except FuturesTimeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Cypher exceeded timeout of {timeout}s.",
        ) from None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cypher error: {e}",
        ) from e
    return CypherResponse(columns=cols, rows=rows, truncated=truncated)
