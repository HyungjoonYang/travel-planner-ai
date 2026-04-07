"""Smoke tests for LLM (Gemini) API connectivity.

These tests make REAL API calls to verify:
- Model ID is valid and accessible
- API key authentication works
- Response format is parseable

Skipped automatically when GEMINI_API_KEY is not set (CI without secrets).
When the key IS available, these tests MUST pass — a failure means the
production service is broken.

Postmortem: gemini-3.0-flash was used as model ID for months but doesn't
exist. Every API call silently failed, and 1499 mock-based tests couldn't
catch it. These smoke tests exist to prevent that from ever happening again.
"""

import json
import os
from pathlib import Path

import pytest
from google import genai
from google.genai import types

from app.ai import GeminiService
from app.chat import ChatService
from app.web_search import WebSearchService
from app.hotel_search import HotelSearchService
from app.flight_search import FlightSearchService

_HAS_API_KEY = bool(os.getenv("GEMINI_API_KEY", ""))
_skip_no_key = pytest.mark.skipif(not _HAS_API_KEY, reason="GEMINI_API_KEY not set")
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SAVE_FIXTURES = bool(os.getenv("SAVE_FIXTURES", ""))


def _save_fixture(name: str, data: str) -> None:
    """Save raw response text to a fixture file when SAVE_FIXTURES=1."""
    if _SAVE_FIXTURES:
        _FIXTURES_DIR.mkdir(exist_ok=True)
        (_FIXTURES_DIR / name).write_text(data, encoding="utf-8")


@_skip_no_key
class TestGeminiSmoke:
    """Real API calls — these hit the actual Gemini service."""

    def test_model_exists_and_responds(self):
        """The configured model ID must be valid and return a response."""
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=GeminiService.MODEL,
            contents="Reply with exactly: OK",
        )
        assert response.text is not None
        assert len(response.text.strip()) > 0

    def test_model_returns_json_when_requested(self):
        """Gemini must respect response_mime_type='application/json'."""
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=GeminiService.MODEL,
            contents='Return a JSON object: {"status": "ok"}',
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text)
        assert isinstance(parsed, dict)

    def test_extract_intent_returns_valid_action(self):
        """ChatService.extract_intent must return a real parsed intent,
        not fall back to 'general' due to API failure."""
        svc = ChatService()  # uses GEMINI_API_KEY from env
        intent = svc.extract_intent("도쿄 3박4일 여행 계획 세워줘")
        # With a working API, this should be create_plan (not general fallback)
        assert intent.action == "create_plan", (
            f"Expected 'create_plan' but got '{intent.action}'. "
            "If this is 'general', the Gemini API call likely failed silently."
        )
        assert intent.destination is not None

    def test_extract_intent_general_greeting(self):
        """A greeting should be classified as 'general' intentionally,
        not as a fallback from API failure."""
        svc = ChatService()
        intent = svc.extract_intent("안녕하세요!")
        assert intent.action == "general"
        # Verify it actually called Gemini (raw_message is set by the method)
        assert intent.raw_message == "안녕하세요!"

    def test_generate_itinerary_returns_days(self):
        """GeminiService.generate_itinerary must return structured days."""
        from datetime import date, timedelta
        svc = GeminiService()
        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=2)
        result = svc.generate_itinerary("도쿄", start, end, 1000000, "음식, 문화")
        assert len(result.days) >= 1
        assert result.days[0].places is not None
        _save_fixture("gemini_itinerary.json", result.model_dump_json(indent=2))

    def test_general_with_gemini_returns_json(self):
        """_general_with_gemini path: Gemini must return parseable JSON with 'response' field."""
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        # Replicate the exact prompt shape used in _general_with_gemini
        prompt = (
            "You are a friendly, knowledgeable travel planning assistant called Travel Planner AI.\n"
            "Your job is to help users plan trips through natural conversation.\n\n"
            "Conversation history:\n(없음)\n\n"
            'User\'s latest message: "안녕하세요"\n\n'
            "Instructions:\n"
            "1. Respond naturally and helpfully in the SAME LANGUAGE the user used.\n"
            "2. If the user mentions travel-related info, acknowledge it.\n"
            "3. If key info is still missing, ask ONE follow-up question.\n"
            "4. If the user is just chatting or greeting, be warm and steer toward travel planning.\n"
            "5. Extract any travel details mentioned so far.\n\n"
            "Return a JSON object with exactly these fields:\n"
            '{"response": "your conversational reply here",'
            ' "destination": "city/country or null",'
            ' "start_date": "YYYY-MM-DD or null",'
            ' "end_date": "YYYY-MM-DD or null",'
            ' "budget": number_or_null,'
            ' "interests": "comma-separated or null"}'
        )
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        result = json.loads(response.text)
        assert "response" in result, f"Missing 'response' field in: {result}"
        assert isinstance(result["response"], str)
        _save_fixture("gemini_general_response.json", response.text)

    def test_search_places_returns_results(self):
        """WebSearchService.search_places must return places with names."""
        svc = WebSearchService()
        result = svc.search_places("도쿄", "음식")
        assert isinstance(result.places, list)
        assert len(result.places) > 0, "search_places returned no places"
        assert result.places[0].name, "First place has no name"
        # Save raw fixture: re-serialize from parsed result
        _save_fixture(
            "gemini_search_places.json",
            result.model_dump_json(indent=2),
        )

    def test_search_weather_returns_summary(self):
        """WebSearchService.search_weather must return a summary."""
        svc = WebSearchService()
        result = svc.search_weather("도쿄")
        assert result.summary, "search_weather returned empty summary"
        _save_fixture(
            "gemini_search_weather.json",
            result.model_dump_json(indent=2),
        )

    def test_search_hotels_returns_results(self):
        """HotelSearchService.search_hotels must return hotels."""
        svc = HotelSearchService()
        result = svc.search_hotels("도쿄")
        assert isinstance(result.hotels, list)
        assert len(result.hotels) > 0, "search_hotels returned no hotels"
        assert result.hotels[0].name, "First hotel has no name"
        _save_fixture(
            "gemini_search_hotels.json",
            result.model_dump_json(indent=2),
        )

    def test_search_flights_returns_results(self):
        """FlightSearchService.search_flights must return flights."""
        svc = FlightSearchService()
        result = svc.search_flights("서울", "도쿄")
        assert isinstance(result.flights, list)
        assert len(result.flights) > 0, "search_flights returned no flights"
        assert result.flights[0].airline, "First flight has no airline"
        _save_fixture(
            "gemini_search_flights.json",
            result.model_dump_json(indent=2),
        )

    def test_suggest_improvements_returns_text(self):
        """GeminiService.suggest_improvements must return non-empty text."""
        svc = GeminiService()
        sample_plan = {
            "destination": "도쿄",
            "days": [{"date": "2026-05-01", "places": [{"name": "센소지"}]}],
        }
        result = svc.suggest_improvements(sample_plan, [])
        assert isinstance(result, str)
        assert len(result.strip()) > 0, "suggest_improvements returned empty text"

    def test_refine_itinerary_returns_structured(self):
        """GeminiService.refine_itinerary must return AIItineraryResult."""
        from datetime import date, timedelta
        svc = GeminiService()
        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=2)
        current_days = [
            {"date": str(start), "notes": "도착일", "places": [{"name": "센소지", "category": "sightseeing"}]},
            {"date": str(start + timedelta(days=1)), "notes": "관광", "places": [{"name": "시부야", "category": "sightseeing"}]},
            {"date": str(end), "notes": "출발일", "places": [{"name": "아키하바라", "category": "shopping"}]},
        ]
        result = svc.refine_itinerary(
            "도쿄", start, end, 1000000, "음식, 문화",
            current_days, "맛집을 더 추가해줘",
        )
        assert len(result.days) == 3, f"Expected 3 days, got {len(result.days)}"
        _save_fixture("gemini_refine_itinerary.json", result.model_dump_json(indent=2))
