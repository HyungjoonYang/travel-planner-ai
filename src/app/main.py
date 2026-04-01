from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
import app.models  # noqa: F401 — registers ORM models with Base.metadata
from app.routers import ai_plans, calendar, expenses, search, travel_plans

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

app.include_router(travel_plans.router)
app.include_router(expenses.router)
app.include_router(ai_plans.router)
app.include_router(search.router)
app.include_router(calendar.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(_STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
