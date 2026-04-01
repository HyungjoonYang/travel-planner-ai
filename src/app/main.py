from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
import app.models  # noqa: F401 — registers ORM models with Base.metadata
from app.routers import ai_plans, search, travel_plans


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
app.include_router(ai_plans.router)
app.include_router(search.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}
