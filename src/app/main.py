from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
import app.models  # noqa: F401 — registers ORM models with Base.metadata


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


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}
