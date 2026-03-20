from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class GitNexusError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status


async def gitnexus_error_handler(request: Request, exc: GitNexusError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
