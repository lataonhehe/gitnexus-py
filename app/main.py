from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import context, cypher, health, repos
from app.config import get_settings
from app.db.neo4j_client import close_driver, ensure_constraints, get_driver, verify_connectivity
from app.logging_setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    driver = get_driver(get_settings())
    if driver and verify_connectivity(driver):
        try:
            ensure_constraints(driver)
        except Exception:
            pass
    yield
    close_driver()


app = FastAPI(
    title="GitNexus Python",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(repos.router)
app.include_router(cypher.router)
app.include_router(context.router)
