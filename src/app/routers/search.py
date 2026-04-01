"""Search router — GET /search/places and GET /search/hotels for destination research."""
from fastapi import APIRouter, HTTPException, Query

from app.hotel_search import HotelSearchResult, HotelSearchService
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


@router.get("/hotels", response_model=HotelSearchResult)
def search_hotels(
    destination: str = Query(..., min_length=1, description="Travel destination"),
    check_in: str = Query("", description="Check-in date (YYYY-MM-DD)"),
    check_out: str = Query("", description="Check-out date (YYYY-MM-DD)"),
    budget_per_night: int = Query(0, ge=0, description="Maximum budget per night in USD"),
    guests: int = Query(1, ge=1, description="Number of guests"),
):
    """Search for hotels in a destination using AI-powered web search."""
    service = HotelSearchService()
    try:
        return service.search_hotels(destination, check_in, check_out, budget_per_night, guests)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hotel search failed: {exc}")
