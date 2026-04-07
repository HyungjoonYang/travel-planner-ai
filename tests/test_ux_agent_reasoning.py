"""Tests for UX Phase 3: Agent Reasoning Events.

Plan: /markdowns/feat-ux-improvements.md

Covers:
- agent_reasoning SSE events emitted during handler work
- Reasoning content describes what the agent is doing and why
- Each relevant handler emits at least one reasoning event
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

from app.ai import AIItineraryResult, AIDayItinerary, AIPlace
from app.chat import ChatService, Intent
from app.hotel_search import HotelSearchResult, HotelResult
from app.flight_search import FlightSearchResult, FlightResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_events(service: ChatService, session_id: str, message: str) -> list[dict]:
    async def _run():
        events = []
        async for event in service.process_message(session_id, message):
            events.append(event)
        return events
    return asyncio.run(_run())


def _make_itinerary_result() -> AIItineraryResult:
    return AIItineraryResult(
        days=[
            AIDayItinerary(
                date="2026-05-01",
                places=[
                    AIPlace(name="Senso-ji", category="sightseeing", estimated_cost=15),
                    AIPlace(name="Ramen Street", category="food", estimated_cost=12),
                ],
            ),
        ],
        total_estimated_cost=27.0,
    )


def _make_hotel_result() -> HotelSearchResult:
    return HotelSearchResult(
        destination="도쿄",
        hotels=[
            HotelResult(name="Park Hyatt", rating="5.0", price_range="$450/night",
                        address="Shinjuku"),
        ],
    )


def _make_flight_result() -> FlightSearchResult:
    return FlightSearchResult(
        departure_city="Seoul",
        arrival_city="Tokyo",
        flights=[
            FlightResult(airline="ANA", price="$800", departure_time="10:00",
                         arrival_time="13:00", duration="3h", stops="0"),
        ],
    )


# ---------------------------------------------------------------------------
# Phase 3A: agent_reasoning events during create_plan
# ---------------------------------------------------------------------------

class TestCreatePlanReasoning:
    """create_plan handler should emit agent_reasoning events
    explaining what each agent is doing."""

    def test_create_plan_emits_agent_reasoning(self):
        """At least one agent_reasoning event should be emitted during create_plan."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "budget": 2000,
            "raw_message": "도쿄 여행",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 여행")

        reasoning_events = [e for e in events if e["type"] == "agent_reasoning"]
        assert len(reasoning_events) >= 1, "Should emit at least one agent_reasoning event"

    def test_reasoning_event_has_agent_and_content(self):
        """Each agent_reasoning event must have agent name and reasoning text."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "파리",
            "raw_message": "파리 여행",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "파리 여행")

        reasoning_events = [e for e in events if e["type"] == "agent_reasoning"]
        for evt in reasoning_events:
            assert "agent" in evt["data"], "agent_reasoning must have 'agent' field"
            assert "reasoning" in evt["data"], "agent_reasoning must have 'reasoning' field"
            assert evt["data"]["agent"] != ""
            assert evt["data"]["reasoning"] != ""

    def test_reasoning_mentions_destination(self):
        """Reasoning should reference the actual destination being searched."""
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "create_plan",
            "destination": "도쿄",
            "raw_message": "도쿄",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_gemini_svc = MagicMock()
        mock_gemini_svc.generate_itinerary.return_value = _make_itinerary_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", gemini_service=mock_gemini_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄")

        reasoning_events = [e for e in events if e["type"] == "agent_reasoning"]
        all_reasoning = " ".join(e["data"]["reasoning"] for e in reasoning_events)
        assert "도쿄" in all_reasoning or "Tokyo" in all_reasoning.lower(), (
            "Reasoning should mention the destination"
        )


# ---------------------------------------------------------------------------
# Phase 3B: agent_reasoning during search handlers
# ---------------------------------------------------------------------------

class TestSearchHandlerReasoning:
    """Search handlers (hotels, flights) should also emit reasoning events."""

    def test_search_hotels_emits_reasoning(self):
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "search_hotels",
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "budget": 2000,
            "raw_message": "도쿄 호텔 찾아줘",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_hotel_svc = MagicMock()
        mock_hotel_svc.search_hotels.return_value = _make_hotel_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", hotel_search_service=mock_hotel_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 호텔 찾아줘")

        reasoning_events = [e for e in events if e["type"] == "agent_reasoning"]
        assert len(reasoning_events) >= 1, "search_hotels should emit reasoning"
        agents = {e["data"]["agent"] for e in reasoning_events}
        assert "hotel_finder" in agents

    def test_search_flights_emits_reasoning(self):
        mock_client = MagicMock()
        intent_resp = MagicMock()
        intent_resp.text = json.dumps({
            "action": "search_flights",
            "destination": "도쿄",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "raw_message": "도쿄 항공권",
        })
        mock_client.models.generate_content.return_value = intent_resp

        mock_flight_svc = MagicMock()
        mock_flight_svc.search_flights.return_value = _make_flight_result()

        with patch("app.chat.genai.Client", return_value=mock_client):
            svc = ChatService(api_key="fake-key", flight_search_service=mock_flight_svc)
            session = svc.create_session()
            events = _collect_events(svc, session.session_id, "도쿄 항공권")

        reasoning_events = [e for e in events if e["type"] == "agent_reasoning"]
        assert len(reasoning_events) >= 1, "search_flights should emit reasoning"
        agents = {e["data"]["agent"] for e in reasoning_events}
        assert "flight_finder" in agents
