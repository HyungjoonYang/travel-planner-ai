"""Search router — GET /search/places, GET /search/hotels, GET /search/flights for destination research."""
from fastapi import APIRouter, HTTPException, Query

from app.cache import search_cache
from app.flight_search import FlightSearchResult, FlightSearchService
from app.hotel_search import HotelSearchResult, HotelSearchService
from app.web_search import DestinationSearchResult, WebSearchService

router = APIRouter(prefix="/search", tags=["search"])


def _places_cache_key(destination: str, interests: str, category: str) -> str:
    return f"places:{destination.lower()}:{interests.lower()}:{category.lower()}"


def _hotels_cache_key(
    destination: str, check_in: str, check_out: str, budget_per_night: int, guests: int
) -> str:
    return f"hotels:{destination.lower()}:{check_in}:{check_out}:{budget_per_night}:{guests}"


def _flights_cache_key(
    departure_city: str,
    arrival_city: str,
    departure_date: str,
    return_date: str,
    passengers: int,
    max_price: int,
) -> str:
    return (
        f"flights:{departure_city.lower()}:{arrival_city.lower()}"
        f":{departure_date}:{return_date}:{passengers}:{max_price}"
    )


@router.get("/places", response_model=DestinationSearchResult)
def search_places(
    destination: str = Query(..., min_length=1, description="Travel destination"),
    interests: str = Query("", description="Comma-separated interests (e.g. food,culture)"),
    category: str = Query("", description="Place category filter (e.g. food, sightseeing)"),
):
    """Search for places in a destination using AI-powered web search."""
    key = _places_cache_key(destination, interests, category)
    cached = search_cache.get(key)
    if cached is not None:
        return cached

    service = WebSearchService()
    try:
        result = service.search_places(destination, interests, category)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search failed: {exc}")

    search_cache.set(key, result)
    return result


@router.get("/hotels", response_model=HotelSearchResult)
def search_hotels(
    destination: str = Query(..., min_length=1, description="Travel destination"),
    check_in: str = Query("", description="Check-in date (YYYY-MM-DD)"),
    check_out: str = Query("", description="Check-out date (YYYY-MM-DD)"),
    budget_per_night: int = Query(0, ge=0, description="Maximum budget per night in USD"),
    guests: int = Query(1, ge=1, description="Number of guests"),
):
    """Search for hotels in a destination using AI-powered web search."""
    key = _hotels_cache_key(destination, check_in, check_out, budget_per_night, guests)
    cached = search_cache.get(key)
    if cached is not None:
        return cached

    service = HotelSearchService()
    try:
        result = service.search_hotels(destination, check_in, check_out, budget_per_night, guests)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hotel search failed: {exc}")

    search_cache.set(key, result)
    return result


@router.get("/flights", response_model=FlightSearchResult)
def search_flights(
    departure_city: str = Query(..., min_length=1, description="Departure city or airport"),
    arrival_city: str = Query(..., min_length=1, description="Arrival city or airport"),
    departure_date: str = Query("", description="Departure date (YYYY-MM-DD)"),
    return_date: str = Query("", description="Return date for round trips (YYYY-MM-DD)"),
    passengers: int = Query(1, ge=1, description="Number of passengers"),
    max_price: int = Query(0, ge=0, description="Maximum price per person in USD"),
):
    """Search for flights between two cities using AI-powered web search."""
    key = _flights_cache_key(
        departure_city, arrival_city, departure_date, return_date, passengers, max_price
    )
    cached = search_cache.get(key)
    if cached is not None:
        return cached

    service = FlightSearchService()
    try:
        result = service.search_flights(
            departure_city, arrival_city, departure_date, return_date, passengers, max_price
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Flight search failed: {exc}")

    search_cache.set(key, result)
    return result
