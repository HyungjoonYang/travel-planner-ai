"""Golden-file parsing tests — verify parsing code handles real Gemini response shapes.

These tests load fixture files captured from real Gemini API calls and run them
through the actual parsing paths. They run WITHOUT an API key, catching any
mismatch between real response formats and our parsing/model code.

To regenerate fixtures:
    SAVE_FIXTURES=1 GEMINI_API_KEY=... pytest tests/test_llm_smoke.py -v
"""

import json
from pathlib import Path

import pytest

from app.ai import AIItineraryResult
from app.web_search import DestinationSearchResult, WeatherSearchResult, WebSearchService
from app.hotel_search import HotelSearchResult, HotelSearchService
from app.flight_search import FlightSearchResult, FlightSearchService

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _require_fixture(name: str) -> str:
    path = _FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found. Run: "
            "SAVE_FIXTURES=1 GEMINI_API_KEY=... pytest tests/test_llm_smoke.py -v"
        )
    return path.read_text(encoding="utf-8")


class TestParseGeneralResponse:
    def test_has_response_field(self):
        raw = _require_fixture("gemini_general_response.json")
        result = json.loads(raw)
        assert "response" in result
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 0


class TestParseSearchPlaces:
    def test_parses_to_model(self):
        raw = _require_fixture("gemini_search_places.json")
        result = DestinationSearchResult.model_validate_json(raw)
        assert len(result.places) > 0
        assert result.places[0].name

    def test_extract_json_works(self):
        """Verify _extract_json handles the real response shape."""
        raw = _require_fixture("gemini_search_places.json")
        svc = WebSearchService(api_key="dummy")
        # The fixture is already parsed JSON from model_dump_json,
        # but _extract_json should handle it too
        data = svc._extract_json(raw)
        assert "places" in data
        assert len(data["places"]) > 0
        assert "name" in data["places"][0]


class TestParseSearchWeather:
    def test_parses_to_model(self):
        raw = _require_fixture("gemini_search_weather.json")
        result = WeatherSearchResult.model_validate_json(raw)
        assert result.summary


class TestParseSearchHotels:
    def test_parses_to_model(self):
        raw = _require_fixture("gemini_search_hotels.json")
        result = HotelSearchResult.model_validate_json(raw)
        assert len(result.hotels) > 0
        assert result.hotels[0].name

    def test_extract_json_works(self):
        raw = _require_fixture("gemini_search_hotels.json")
        svc = HotelSearchService(api_key="dummy")
        data = svc._extract_json(raw)
        assert "hotels" in data
        assert len(data["hotels"]) > 0
        assert "name" in data["hotels"][0]


class TestParseSearchFlights:
    def test_parses_to_model(self):
        raw = _require_fixture("gemini_search_flights.json")
        result = FlightSearchResult.model_validate_json(raw)
        assert len(result.flights) > 0
        assert result.flights[0].airline

    def test_extract_json_works(self):
        raw = _require_fixture("gemini_search_flights.json")
        svc = FlightSearchService(api_key="dummy")
        data = svc._extract_json(raw)
        assert "flights" in data
        assert len(data["flights"]) > 0
        assert "airline" in data["flights"][0]


class TestParseItinerary:
    def test_parses_to_model(self):
        raw = _require_fixture("gemini_itinerary.json")
        result = AIItineraryResult.model_validate_json(raw)
        assert len(result.days) >= 1
        assert result.days[0].places is not None


class TestParseRefineItinerary:
    def test_parses_to_model(self):
        raw = _require_fixture("gemini_refine_itinerary.json")
        result = AIItineraryResult.model_validate_json(raw)
        assert len(result.days) >= 1
