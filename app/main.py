from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, repos
from app.config import get_settings
from app.core.errors import GitNexusError, gitnexus_error_handler
from app.core.logging import setup_logging
from app.db.neo4j_client import close_driver, ensure_constraints, get_driver, verify_connectivity


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    driver = get_driver(get_settings())
    if driver and verify_connectivity(driver):
        try:
            ensure_constraints(driver)
        except Exception:
            pass
    yield
    close_driver()


app = FastAPI(
    title="GitNexus Backend",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_exception_handler(GitNexusError, gitnexus_error_handler)

app.include_router(health.router)
app.include_router(repos.router)
