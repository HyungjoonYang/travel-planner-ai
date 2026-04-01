from contextlib import asynccontextmanager
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app.cache import search_cache
from app.database import init_db
import app.models  # noqa: F401 — registers ORM models with Base.metadata
from app.routers import ai_plans, calendar, expenses, search, travel_plans

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Travel Planner AI",
    description="AI-powered travel planning API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    request_id = getattr(request.state, "request_id", "-")
    logger.error("DB integrity error request_id=%s: %s", request_id, exc, exc_info=False)
    return JSONResponse(
        status_code=409,
        content={"detail": "Data conflict: a resource with the same key already exists."},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    request_id = getattr(request.state, "request_id", "-")
    logger.error("DB operational error request_id=%s: %s", request_id, exc, exc_info=False)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable. Please retry."},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    request_id = getattr(request.state, "request_id", "-")
    logger.error("Unhandled DB error request_id=%s: %s", request_id, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected database error occurred."},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Let FastAPI's own HTTPException handler run first; only catch true unhandled errors.
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    if isinstance(exc, FastAPIHTTPException):
        raise exc
    request_id = getattr(request.state, "request_id", "-")
    logger.error("Unhandled exception request_id=%s: %s", request_id, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
        headers={"X-Request-ID": request_id},
    )


app.include_router(travel_plans.router)
app.include_router(expenses.router)
app.include_router(ai_plans.router)
app.include_router(search.router)
app.include_router(calendar.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/cache/stats", tags=["cache"])
def cache_stats():
    """Return search-result cache statistics."""
    return search_cache.stats()


@app.delete("/cache", tags=["cache"])
def cache_clear():
    """Evict all cached search results. Useful after data updates."""
    cleared = search_cache.clear()
    return {"cleared": cleared}


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(_STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
