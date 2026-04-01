"""Search router — GET /search/places for destination research."""
from fastapi import APIRouter, HTTPException, Query

from app.web_search import DestinationSearchResult, WebSearchService

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/places", response_model=DestinationSearchResult)
def search_places(
    destination: str = Query(..., min_length=1, description="Travel destination"),
    interests: str = Query("", description="Comma-separated interests (e.g. food,culture)"),
    category: str = Query("", description="Place category filter (e.g. food, sightseeing)"),
):
    """Search for places in a destination using AI-powered web search."""
    service = WebSearchService()
    try:
        return service.search_places(destination, interests, category)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search failed: {exc}")
